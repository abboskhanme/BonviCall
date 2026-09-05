import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.kapt)
    alias(libs.plugins.hilt)
}

/**
 * The LAN address of a developer's machine, for testing on a real handset.
 *
 * Set it in `local.properties` (gitignored) as
 * `bonvicall.devHost=192.168.1.23`, or pass `-Pbonvicall.devHost=…`. It is
 * substituted into the DEBUG network security config only; a release build
 * never sees it. Unset, it falls back to the emulator loopback, so the default
 * behaviour is unchanged and nobody's home IP is ever committed.
 */
val devHost: String? = (project.findProperty("bonvicall.devHost") as String?)
    ?: runCatching {
        Properties().apply {
            rootProject.file("local.properties").inputStream().use(::load)
        }.getProperty("bonvicall.devHost")
    }.getOrNull()

/**
 * Substitutes `__DEV_HOST__` into the debug network security config.
 *
 * The TEMPLATE lives outside `res/` on purpose — a tracked copy inside `res/`
 * plus a generated one would be a duplicate-resource error. A developer testing
 * on a real phone changes one line in `local.properties` instead of editing a
 * tracked file, which is how somebody else's IP gets committed and how a
 * "temporary" wildcard gets added.
 */
val generateDebugNetworkConfig by tasks.registering {
    val template = layout.projectDirectory.file("src/debug/network_security_config.template.xml")
    val output = layout.buildDirectory.file("generated/res/devhost/xml/network_security_config.xml")
    inputs.file(template)
    inputs.property("devHost", devHost ?: "")
    outputs.file(output)

    doLast {
        // Already covered by the static entries. Emitting the placeholder line
        // anyway would produce a duplicate <domain>, which lint rejects as
        // fatal — correctly, since a duplicated host is a config nobody has
        // read.
        val alreadyListed = setOf("10.0.2.2", "127.0.0.1", "localhost")
        val host = devHost?.trim()?.takeIf { it.isNotEmpty() && it !in alreadyListed }

        val rendered = template.asFile.readLines()
            .mapNotNull { line ->
                when {
                    !line.contains("__DEV_HOST__") -> line
                    host != null -> line.replace("__DEV_HOST__", host)
                    // No LAN host configured: drop the line entirely rather
                    // than shipping a placeholder as a domain name.
                    else -> null
                }
            }
            .joinToString("\n", postfix = "\n")

        output.get().asFile.apply { parentFile.mkdirs() }.writeText(rendered)
    }
}

/**
 * The release signing keystore.
 *
 * ⚠️ **Losing this key means no device can ever be updated again.** Android
 * refuses to install an update signed by a different key, and with no Play
 * Store to re-publish through (N33) the only remedy is uninstall-and-reinstall
 * on every handset in the fleet — which destroys the local queue on each one.
 * `docs/APK-SIGNING.md` is the backup procedure and it is part of T81, not an
 * afterthought.
 *
 * Credentials come from `keystore.properties` (gitignored) or the environment,
 * never from this file. An unsigned release still builds, so CI and a
 * developer without the key are not blocked — `signingConfig` is simply absent
 * and `assembleRelease` produces `-unsigned.apk`.
 */
val keystoreProperties: Properties? = rootProject.file("keystore.properties")
    .takeIf { it.isFile }
    ?.let { file -> Properties().apply { file.inputStream().use(::load) } }

fun secret(key: String, env: String): String? =
    keystoreProperties?.getProperty(key) ?: System.getenv(env)

android {
    namespace = "uz.bonvi.call"
    compileSdk = 34

    defaultConfig {
        applicationId = "uz.bonvi.call"

        // N32. The fleet inventory (W01) found nothing below this.
        minSdk = 26

        // targetSdk is NOT set here on purpose — see productFlavors below.
        // S1-RECORDING.md proved targetSdk is load-bearing for BOTH recording
        // paths, so it is a build variant that M0 settles with measurements,
        // not a constant someone edits at 2 a.m.

        versionCode = 1
        versionName = "1.0.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables { useSupportLibrary = true }
    }

    // ── The captureTarget dimension (SPEC §7.2) ───────────────────────────
    // Two flavours, both buildable, both shippable. Release 1 ships whichever
    // M0 selects; the other staying buildable is what makes R9 ("a future
    // Android release breaks the app") a rebuild rather than a rewrite.
    flavorDimensions += "captureTarget"
    productFlavors {
        create("legacy28") {
            dimension = "captureTarget"
            // 28 deliberately. At targetSdk 29+ Android restricts the other
            // party's audio and the phoneCall foreground-service type; at 28,
            // in legacy mode, many handsets record both sides. It is also what
            // keeps the raw-path OEM harvest working — scoped storage closes
            // that door. Not for the Play Store: the APK is self-hosted (N33).
            targetSdk = 28
            buildConfigField("String", "APP_VARIANT", "\"legacy28\"")
        }
        create("modern34") {
            dimension = "captureTarget"
            // Better on every axis except the one that matters most, which is
            // why M0 measures rather than assumes. Reaches the OEM folder
            // through MANAGE_EXTERNAL_STORAGE + MediaStore instead of raw paths.
            targetSdk = 34
            buildConfigField("String", "APP_VARIANT", "\"modern34\"")
        }
    }

    sourceSets {
        getByName("debug") {
            res.srcDir(layout.buildDirectory.dir("generated/res/devhost"))
        }
    }

    signingConfigs {
        create("release") {
            val storePath = secret("storeFile", "BONVICALL_KEYSTORE")
            if (storePath != null) {
                storeFile = rootProject.file(storePath)
                storePassword = secret("storePassword", "BONVICALL_KEYSTORE_PASSWORD")
                keyAlias = secret("keyAlias", "BONVICALL_KEY_ALIAS") ?: "bonvicall"
                keyPassword = secret("keyPassword", "BONVICALL_KEY_PASSWORD")

                // v2 and v3 as well as v1. The APK is side-loaded onto API
                // 26–34; v1 alone is rejected from API 30, and v2+ is what
                // makes the install fast enough not to look broken during
                // N40's fifteen minutes.
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        release {
            // Absent when there is no keystore, which yields -unsigned.apk
            // rather than a build failure: CI and a developer without the key
            // must still be able to prove the release variant compiles.
            signingConfig = signingConfigs.getByName("release")
                .takeIf { it.storeFile != null }

            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
        debug {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    buildFeatures {
        compose = true
        buildConfig = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = libs.versions.composeCompiler.get()
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = true

            // android.jar's stubs throw "not mocked" by default. The classes
            // that matter here are pure — Clock's MONOTONIC reading is the only
            // Android call in the detector path — and returning 0 from it is
            // exactly what a test wants: durations become deterministic instead
            // of depending on wall-clock luck. Anything that genuinely needs
            // Android behaviour belongs in an instrumented test.
            isReturnDefaultValues = true
            all {
                // ArchitectureRulesTest and the manifest tests read source files
                // relative to the repository, so they need to know where it is
                // whatever directory Gradle chooses to fork the JVM in.
                it.systemProperty("bonvicall.repoRoot", rootProject.projectDir.parentFile.absolutePath)
                it.systemProperty("bonvicall.appDir", projectDir.absolutePath)
            }
        }
    }

    packaging {
        resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" }
    }

    lint {
        // A lint error fails the build. The alternative is a warning nobody
        // reads on a project whose install friction is already the top risk.
        warningsAsErrors = false
        abortOnError = true
        checkDependencies = false
        lintConfig = file("lint.xml")
    }
}

// The substituted file has to exist before ANY task that scans the debug
// resource directories — AGP has several (mapSourceSetPaths, mergeResources,
// packageResources) and naming them individually is a list that goes stale.
// preBuild runs before all of them.
tasks.named("preBuild") { dependsOn(generateDebugNetworkConfig) }

kapt {
    correctErrorTypes = true
    arguments {
        // The Room schema is exported and COMMITTED. Every migration is written
        // against the previous schema, and the thing a wrong migration destroys
        // here is the upload queue — calls that happened and had not reached the
        // server yet (N8). A schema you cannot diff is a migration you cannot
        // review.
        arg("room.schemaLocation", "$projectDir/schemas")
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    debugImplementation(libs.compose.ui.tooling)

    implementation(libs.navigation.compose)

    implementation(libs.lifecycle.runtime.ktx)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.service)

    implementation(libs.hilt.android)
    kapt(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)
    implementation(libs.hilt.work)
    kapt(libs.hilt.work.compiler)

    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    kapt(libs.room.compiler)

    implementation(libs.retrofit)
    implementation(libs.retrofit.converter.moshi)
    implementation(libs.moshi)
    implementation(libs.moshi.kotlin)
    kapt(libs.moshi.kotlin.codegen)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)

    implementation(libs.work.runtime.ktx)
    implementation(libs.datastore.preferences)

    implementation(libs.coroutines.core)
    implementation(libs.coroutines.android)

    implementation(libs.timber)

    testImplementation(libs.json)
    testImplementation(libs.junit)
    testImplementation(libs.truth)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core)
    testImplementation(libs.coroutines.test)
}
