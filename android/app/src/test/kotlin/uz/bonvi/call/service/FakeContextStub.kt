package uz.bonvi.call.service

import android.content.Context

/**
 * A `Context` that is never used.
 *
 * `CallDetector` holds one only for `currentCallState()`, which the tests do
 * not exercise — everything they DO exercise is pure decision logic, which is
 * the point of keeping the rules out of the Android callbacks. A mocking
 * framework for one unused reference would be a dependency and a habit.
 */
object FakeContextStub {
    val instance: Context = UnusedContext()

    private class UnusedContext : Context() {
        override fun getSystemService(name: String): Any? = null
        override fun getApplicationContext(): Context = this

        // Everything below is unreachable in these tests. Failing loudly beats
        // returning a plausible default that hides a real call.
        override fun getAssets() = unreachable()
        override fun getResources() = unreachable()
        override fun getPackageManager() = unreachable()
        override fun getContentResolver() = unreachable()
        override fun getMainLooper() = unreachable()
        override fun getPackageName() = "uz.bonvi.call"
        override fun getApplicationInfo() = unreachable()
        override fun getPackageResourcePath() = unreachable()
        override fun getPackageCodePath() = unreachable()
        override fun getSharedPreferences(name: String?, mode: Int) = unreachable()
        override fun moveSharedPreferencesFrom(sourceContext: Context?, name: String?) = unreachable()
        override fun deleteSharedPreferences(name: String?) = unreachable()
        override fun openFileInput(name: String?) = unreachable()
        override fun openFileOutput(name: String?, mode: Int) = unreachable()
        override fun deleteFile(name: String?) = unreachable()
        override fun getFileStreamPath(name: String?) = unreachable()
        override fun getDataDir() = unreachable()
        override fun getFilesDir() = unreachable()
        override fun getNoBackupFilesDir() = unreachable()
        override fun getExternalFilesDir(type: String?) = unreachable()
        override fun getExternalFilesDirs(type: String?) = unreachable()
        override fun getObbDir() = unreachable()
        override fun getObbDirs() = unreachable()
        override fun getCacheDir() = unreachable()
        override fun getCodeCacheDir() = unreachable()
        override fun getExternalCacheDir() = unreachable()
        override fun getExternalCacheDirs() = unreachable()
        override fun getExternalMediaDirs() = unreachable()
        override fun fileList() = unreachable()
        override fun getDir(name: String?, mode: Int) = unreachable()
        override fun openOrCreateDatabase(n: String?, m: Int, f: android.database.sqlite.SQLiteDatabase.CursorFactory?) = unreachable()
        override fun openOrCreateDatabase(n: String?, m: Int, f: android.database.sqlite.SQLiteDatabase.CursorFactory?, e: android.database.DatabaseErrorHandler?) = unreachable()
        override fun moveDatabaseFrom(sourceContext: Context?, name: String?) = unreachable()
        override fun deleteDatabase(name: String?) = unreachable()
        override fun getDatabasePath(name: String?) = unreachable()
        override fun databaseList() = unreachable()
        @Deprecated("Deprecated in Java") override fun getWallpaper() = unreachable()
        @Deprecated("Deprecated in Java") override fun peekWallpaper() = unreachable()
        @Deprecated("Deprecated in Java") override fun getWallpaperDesiredMinimumWidth() = unreachable()
        @Deprecated("Deprecated in Java") override fun getWallpaperDesiredMinimumHeight() = unreachable()
        @Deprecated("Deprecated in Java") override fun setWallpaper(bitmap: android.graphics.Bitmap?) = unreachable()
        @Deprecated("Deprecated in Java") override fun setWallpaper(data: java.io.InputStream?) = unreachable()
        @Deprecated("Deprecated in Java") override fun clearWallpaper() = unreachable()
        override fun startActivity(intent: android.content.Intent?) = unreachable()
        override fun startActivity(intent: android.content.Intent?, options: android.os.Bundle?) = unreachable()
        override fun startActivities(intents: Array<out android.content.Intent>?) = unreachable()
        override fun startActivities(intents: Array<out android.content.Intent>?, options: android.os.Bundle?) = unreachable()
        override fun startIntentSender(i: android.content.IntentSender?, f: android.content.Intent?, a: Int, b: Int, c: Int) = unreachable()
        override fun startIntentSender(i: android.content.IntentSender?, f: android.content.Intent?, a: Int, b: Int, c: Int, o: android.os.Bundle?) = unreachable()
        override fun sendBroadcast(intent: android.content.Intent?) = unreachable()
        override fun sendBroadcast(intent: android.content.Intent?, receiverPermission: String?) = unreachable()
        override fun sendOrderedBroadcast(intent: android.content.Intent?, receiverPermission: String?) = unreachable()
        override fun sendOrderedBroadcast(i: android.content.Intent, r: String?, rr: android.content.BroadcastReceiver?, s: android.os.Handler?, c: Int, d: String?, e: android.os.Bundle?) = unreachable()
        override fun sendBroadcastAsUser(i: android.content.Intent?, u: android.os.UserHandle?) = unreachable()
        override fun sendBroadcastAsUser(i: android.content.Intent?, u: android.os.UserHandle?, p: String?) = unreachable()
        override fun sendOrderedBroadcastAsUser(i: android.content.Intent?, u: android.os.UserHandle?, p: String?, r: android.content.BroadcastReceiver?, s: android.os.Handler?, c: Int, d: String?, e: android.os.Bundle?) = unreachable()
        @Deprecated("Deprecated in Java") override fun sendStickyBroadcast(intent: android.content.Intent?) = unreachable()
        @Deprecated("Deprecated in Java") override fun sendStickyOrderedBroadcast(i: android.content.Intent?, r: android.content.BroadcastReceiver?, s: android.os.Handler?, c: Int, d: String?, e: android.os.Bundle?) = unreachable()
        @Deprecated("Deprecated in Java") override fun removeStickyBroadcast(intent: android.content.Intent?) = unreachable()
        @Deprecated("Deprecated in Java") override fun sendStickyBroadcastAsUser(i: android.content.Intent?, u: android.os.UserHandle?) = unreachable()
        @Deprecated("Deprecated in Java") override fun sendStickyOrderedBroadcastAsUser(i: android.content.Intent?, u: android.os.UserHandle?, r: android.content.BroadcastReceiver?, s: android.os.Handler?, c: Int, d: String?, e: android.os.Bundle?) = unreachable()
        @Deprecated("Deprecated in Java") override fun removeStickyBroadcastAsUser(i: android.content.Intent?, u: android.os.UserHandle?) = unreachable()
        override fun registerReceiver(r: android.content.BroadcastReceiver?, f: android.content.IntentFilter?) = unreachable()
        override fun registerReceiver(r: android.content.BroadcastReceiver?, f: android.content.IntentFilter?, flags: Int) = unreachable()
        override fun registerReceiver(r: android.content.BroadcastReceiver?, f: android.content.IntentFilter?, p: String?, s: android.os.Handler?) = unreachable()
        override fun registerReceiver(r: android.content.BroadcastReceiver?, f: android.content.IntentFilter?, p: String?, s: android.os.Handler?, flags: Int) = unreachable()
        override fun unregisterReceiver(receiver: android.content.BroadcastReceiver?) = unreachable()
        override fun startService(service: android.content.Intent?) = unreachable()
        override fun startForegroundService(service: android.content.Intent?) = unreachable()
        override fun stopService(name: android.content.Intent?) = unreachable()
        override fun bindService(s: android.content.Intent, c: android.content.ServiceConnection, f: Int) = unreachable()
        override fun unbindService(conn: android.content.ServiceConnection) = unreachable()
        override fun startInstrumentation(c: android.content.ComponentName, p: String?, a: android.os.Bundle?) = unreachable()
        override fun getSystemServiceName(serviceClass: Class<*>) = null
        override fun checkPermission(permission: String, pid: Int, uid: Int) = unreachable()
        override fun checkCallingPermission(permission: String) = unreachable()
        override fun checkCallingOrSelfPermission(permission: String) = unreachable()
        override fun checkSelfPermission(permission: String) = unreachable()
        override fun enforcePermission(p: String, pid: Int, uid: Int, m: String?) = unreachable()
        override fun enforceCallingPermission(permission: String, message: String?) = unreachable()
        override fun enforceCallingOrSelfPermission(permission: String, message: String?) = unreachable()
        override fun grantUriPermission(p: String?, uri: android.net.Uri?, m: Int) = unreachable()
        override fun revokeUriPermission(uri: android.net.Uri?, m: Int) = unreachable()
        override fun revokeUriPermission(p: String?, uri: android.net.Uri?, m: Int) = unreachable()
        override fun checkUriPermission(uri: android.net.Uri?, pid: Int, uid: Int, m: Int) = unreachable()
        override fun checkUriPermission(uri: android.net.Uri?, p: String?, w: String?, pid: Int, uid: Int, m: Int) = unreachable()
        override fun checkCallingUriPermission(uri: android.net.Uri?, m: Int) = unreachable()
        override fun checkCallingOrSelfUriPermission(uri: android.net.Uri?, m: Int) = unreachable()
        override fun enforceUriPermission(uri: android.net.Uri?, pid: Int, uid: Int, m: Int, msg: String?) = unreachable()
        override fun enforceUriPermission(uri: android.net.Uri?, p: String?, w: String?, pid: Int, uid: Int, m: Int, msg: String?) = unreachable()
        override fun enforceCallingUriPermission(uri: android.net.Uri?, m: Int, msg: String?) = unreachable()
        override fun enforceCallingOrSelfUriPermission(uri: android.net.Uri?, m: Int, msg: String?) = unreachable()
        override fun createPackageContext(packageName: String?, flags: Int) = unreachable()
        override fun createContextForSplit(splitName: String?) = unreachable()
        override fun createConfigurationContext(c: android.content.res.Configuration) = unreachable()
        override fun createDisplayContext(display: android.view.Display) = unreachable()
        override fun createDeviceProtectedStorageContext() = unreachable()
        override fun isDeviceProtectedStorage() = unreachable()
        override fun getTheme() = unreachable()
        override fun setTheme(resid: Int) = unreachable()
        override fun getClassLoader() = unreachable()
        override fun getMainExecutor() = unreachable()

        private fun unreachable(): Nothing =
            error("This Context is a stub; CallDetector's tests exercise pure logic only")
    }
}
