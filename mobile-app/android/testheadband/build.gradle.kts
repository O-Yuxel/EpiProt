plugins {
    alias(libs.plugins.android.application)
}

// Test headband for a second Android device: advertises the EpiProt headband service over real
// Bluetooth LE and streams the virtual-headband demo (device-firmware/PROTOCOL.md). Not part of the product.
android {
    namespace = "org.epiprot.testheadband"
    compileSdk = 36
    defaultConfig {
        applicationId = "org.epiprot.testheadband"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].assets.srcDirs("../app/src/main/assets/demo")
    androidResources { noCompress += listOf("ehb") }
}

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}
