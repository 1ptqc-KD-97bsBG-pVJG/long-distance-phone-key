"""Small dependency-free Android build using the locally installed SDK/JDK."""
import os
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parent.parent
sdk = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "Library/Android/sdk"))
jdk = Path(os.environ.get("PHONE_KEY_JDK", "/opt/homebrew/opt/openjdk@17"))
tools = sdk / "build-tools/35.0.0"
android = sdk / "platforms/android-35/android.jar"
out = root / "build/android"
classes = out / "classes"
classes.mkdir(parents=True, exist_ok=True)
def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)
run(jdk / "bin/javac", "-source", "8", "-target", "8", "-classpath", android,
    "-d", classes, *sorted((root / "android/src").rglob("*.java")))
jar = out / "classes.jar"
run(jdk / "bin/jar", "cf", jar, "-C", classes, ".")
run(jdk / "bin/java", "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8",
    "--lib", android, "--min-api", "28", "--output", out, jar)
apk = out / "phone-key-lab.apk"
run(tools / "aapt", "package", "-f", "-M", root / "android/AndroidManifest.xml", "-I", android, "-F", apk)
with zipfile.ZipFile(apk, "a") as archive:
    archive.write(out / "classes.dex", "classes.dex")
key = out / "debug.keystore"
if not key.exists():
    run(jdk / "bin/keytool", "-genkeypair", "-keystore", key, "-storepass", "android", "-keypass", "android",
        "-alias", "lab", "-dname", "CN=Phone Key Lab", "-keyalg", "RSA", "-validity", "3650")
run(jdk / "bin/java", "-jar", tools / "lib/apksigner.jar", "sign", "--ks", key,
    "--ks-key-alias", "lab", "--ks-pass", "pass:android", apk)
print(apk)
