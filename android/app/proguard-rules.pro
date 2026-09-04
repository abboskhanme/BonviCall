# R8 rules for the release build.

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
