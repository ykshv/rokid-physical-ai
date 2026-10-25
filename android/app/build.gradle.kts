plugins { id("com.android.application") }

android {
    namespace = "io.github.ykshv.rokidphysicalai"
    compileSdk = 37
    defaultConfig {
        applicationId = "io.github.ykshv.rokidphysicalai"
        minSdk = 32
        targetSdk = 32 // Stock Rokid firmware qualification target; not a Play Store build.
        versionCode = 1
        versionName = "0.1.0-dev1"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    lint { abortOnError = true; disable += "ExpiredTargetSdkVersion" }
}
dependencies { implementation("com.squareup.okhttp3:okhttp:5.5.1") }
