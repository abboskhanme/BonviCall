# R8 rules for the release build.

# ═══════════════════════════════════════════════════════════════════════════
# androidx.lifecycle 2.8.x finds Compose 1.6's LocalLifecycleOwner BY NAME.
#
# `androidx.lifecycle.compose.LocalLifecycleOwnerKt`'s static initialiser does
# this, reflectively, inside a runCatching:
#
#     ClassLoader.loadClass("androidx.compose.ui.platform.AndroidCompositionLocals_androidKt")
#         .getMethod("getLocalLifecycleOwner")
#
# It is how one CompositionLocal serves both the Compose 1.6 world (where
# AndroidComposeView provides the Compose UI one) and the 1.7 world. R8 renamed
# that class to `g0.Q`, the lookup threw, and the fallback is
# `compositionLocalOf { error("CompositionLocal LocalLifecycleOwner not present") }`.
#
# The result was a release-only crash on the FIRST composition that reads it —
# every screen, because they all call `collectAsStateWithLifecycle`. Debug
# builds are not minified, so nine field days on debug APKs never saw it and
# the first signed APK died on the phone it was installed on.
#
# `verifyLifecycleReflectionSurvivesR8` in app/build.gradle.kts fails the build
# if this rule ever stops working, because the symptom is invisible until the
# APK is on a handset.
# ═══════════════════════════════════════════════════════════════════════════
-keep class androidx.compose.ui.platform.AndroidCompositionLocals_androidKt {
    public static ** getLocalLifecycleOwner();
}

# Moshi generates adapters by reflection over the generated classes; the DTOs
# themselves are generated from contract/openapi-device-v1.json, so a field
# stripped here is a field the server silently stops receiving.
-keep class uz.bonvi.call.data.remote.dto.** { *; }
-keepclassmembers class uz.bonvi.call.data.remote.dto.** { *; }

# Room entities and DAOs.
-keep class uz.bonvi.call.data.local.** { *; }

# Retrofit interfaces are proxied at runtime.
-keepattributes Signature, InnerClasses, EnclosingMethod, RuntimeVisibleAnnotations
-keep,allowobfuscation interface uz.bonvi.call.data.remote.api.**

# OkHttp / Okio.
-dontwarn okhttp3.**
-dontwarn okio.**

# Timber.
-dontwarn org.jetbrains.annotations.**
