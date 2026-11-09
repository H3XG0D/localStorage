plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.focusvpn.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.focusvpn.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 8
        versionName = "0.1.7"
        val apiBase = (project.findProperty("FOCUSVPN_API_BASE") as String?)
            ?: System.getenv("FOCUSVPN_API_BASE")
            ?: "http://10.0.2.2:18080"
        buildConfigField("String", "DEFAULT_API_BASE", "\"$apiBase\"")
        val botUsername = (project.findProperty("FOCUSVPN_BOT_USERNAME") as String?)
            ?: System.getenv("FOCUSVPN_BOT_USERNAME")
            ?: "focusvpn1_bot"
        buildConfigField("String", "TELEGRAM_BOT_USERNAME", "\"$botUsername\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("release") {
            val store = System.getenv("FOCUSVPN_STORE_FILE")
                ?: (project.findProperty("FOCUSVPN_STORE_FILE") as String?)
            val storePass = System.getenv("FOCUSVPN_STORE_PASSWORD")
                ?: (project.findProperty("FOCUSVPN_STORE_PASSWORD") as String?)
            val keyAlias = System.getenv("FOCUSVPN_KEY_ALIAS")
                ?: (project.findProperty("FOCUSVPN_KEY_ALIAS") as String?)
            val keyPass = System.getenv("FOCUSVPN_KEY_PASSWORD")
                ?: (project.findProperty("FOCUSVPN_KEY_PASSWORD") as String?)
            if (!store.isNullOrBlank() && !storePass.isNullOrBlank()
                && !keyAlias.isNullOrBlank() && !keyPass.isNullOrBlank()
            ) {
                storeFile = file(store)
                storePassword = storePass
                this.keyAlias = keyAlias
                keyPassword = keyPass
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            val sc = signingConfigs.findByName("release")
            if (sc?.storeFile != null) {
                signingConfig = sc
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64")
            isUniversalApk = false
        }
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
        jniLibs {
            useLegacyPackaging = true
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.navigation:navigation-compose:2.8.4")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.bouncycastle:bcprov-jdk18on:1.78.1")
    val libxray = rootProject.file(".libxray/libXray.aar")
    if (!libxray.exists()) {
        throw GradleException("Missing ${libxray.path}. Run scripts/fetch-libxray-android.sh")
    }
    implementation(files(libxray))

    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    testImplementation("org.bouncycastle:bcprov-jdk18on:1.78.1")
}
