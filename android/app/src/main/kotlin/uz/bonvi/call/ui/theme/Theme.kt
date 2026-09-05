package uz.bonvi.call.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Bonvi navy — the same accent the panel uses, so one product looks like one
 *  product on a phone and on a screen. */
private val BrandNavy = Color(0xFF1D4E79)
private val BrandNavyLight = Color(0xFF6FA8DC)

private val LightColors = lightColorScheme(
    primary = BrandNavy,
    onPrimary = Color.White,
    secondary = BrandNavy,
)

private val DarkColors = darkColorScheme(
    primary = BrandNavyLight,
    onPrimary = Color(0xFF0B1A26),
    secondary = BrandNavyLight,
)

/**
 * No dynamic colour. The enrolment screens are photographed for the Uzbek
 * install guide (T107), and a theme that changes with the user's wallpaper
 * would make every screenshot wrong on somebody's phone.
 */
@Composable
fun BonviCallTheme(
    // TEMPORARY, for on-device testing: forced light so a tester can see at a
    // glance that the build on the phone is the new one. Restore
    // `isSystemInDarkTheme()` once the install path is proven.
    darkTheme: Boolean = false,
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content,
    )
}
