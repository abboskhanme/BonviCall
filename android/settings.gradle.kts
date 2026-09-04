pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "BonviCall"

// ONE Gradle module (SPEC §7.1, CONVENTIONS-CLIENT.md §5). Multi-module Gradle
// buys build parallelism and enforced dependency boundaries; this project needs
// neither, and two product flavours multiplied by several modules is exactly
// where Hilt binding turns fiddly for no benefit. The boundary that matters is
// the privacy boundary, and that one is enforced by a TYPE
// (OemHarvestStrategy.locate(Decision.Capture, …)), which a Gradle module
// boundary would not improve. The package-level rules are enforced by
// ArchitectureRulesTest instead.
include(":app")
