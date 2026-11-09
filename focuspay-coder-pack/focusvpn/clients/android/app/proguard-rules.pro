# Release R8. Compose, OkHttp, and kotlinx.serialization ship their own
# consumer rules (Serializable + @SerialName stay intact). Manifest components
# are kept by the Android Gradle Plugin.

# gomobile JNI. Renaming these classes or methods breaks libXray native calls.
-keep class libXray.** { *; }
-keep class go.** { *; }

# Tink (androidx.security) references these annotations; they are not on the runtime classpath.
-dontwarn com.google.errorprone.annotations.CanIgnoreReturnValue
-dontwarn com.google.errorprone.annotations.CheckReturnValue
-dontwarn com.google.errorprone.annotations.Immutable
-dontwarn com.google.errorprone.annotations.RestrictedApi
