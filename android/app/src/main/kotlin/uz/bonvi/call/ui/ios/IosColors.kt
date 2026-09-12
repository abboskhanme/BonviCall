package uz.bonvi.call.ui.ios

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color

/**
 * The iOS system palette, as raw constants.
 *
 * These are Apple's published UIColor system values. They are exposed as
 * constants for the rare case where one is needed outside a composable; every
 * screen should read [IosPalette] instead, because only that one answers the
 * light/dark question.
 *
 * Nothing here is a Bonvi brand colour on purpose. The app is installed on a
 * salesperson's own phone next to their other apps, and the thing that makes a
 * screen read as "part of the phone" rather than "a program somebody installed"
 * is that the blues and greys are the ones the rest of the phone uses.
 */
object IosColors {
    // ── Accents ──────────────────────────────────────────────────────────
    val SystemBlue = Color(0xFF007AFF)
    val SystemBlueDark = Color(0xFF0A84FF)
    val SystemGreen = Color(0xFF34C759)
    val SystemGreenDark = Color(0xFF30D158)
    val SystemRed = Color(0xFFFF3B30)
    val SystemRedDark = Color(0xFFFF453A)
    val SystemOrange = Color(0xFFFF9500)
    val SystemOrangeDark = Color(0xFFFF9F0A)

    // ── Greys. systemGray is the same in both appearances; 2..6 invert. ──
    val SystemGray = Color(0xFF8E8E93)
    val SystemGray2 = Color(0xFFAEAEB2)
    val SystemGray3 = Color(0xFFC7C7CC)
    val SystemGray4 = Color(0xFFD1D1D6)
    val SystemGray5 = Color(0xFFE5E5EA)
    val SystemGray6 = Color(0xFFF2F2F7)

    val SystemGray2Dark = Color(0xFF636366)
    val SystemGray3Dark = Color(0xFF48484A)
    val SystemGray4Dark = Color(0xFF3A3A3C)
    val SystemGray5Dark = Color(0xFF2C2C2E)
    val SystemGray6Dark = Color(0xFF1C1C1E)

    // ── Backgrounds and separators ───────────────────────────────────────
    val GroupedBackground = Color(0xFFF2F2F7)
    val GroupedBackgroundDark = Color(0xFF000000)
    val SecondaryGroupedBackground = Color(0xFFFFFFFF)
    val SecondaryGroupedBackgroundDark = Color(0xFF1C1C1E)
    val Separator = Color(0xFFC6C6C8)
    val SeparatorDark = Color(0xFF38383A)

    // ── Labels. Secondary and tertiary are translucent, as on iOS: they
    //    have to sit on both the white card and the grey background. ───────
    val Label = Color(0xFF000000)
    val LabelDark = Color(0xFFFFFFFF)
    val SecondaryLabel = Color(0x993C3C43) // #3C3C43 @ 60%
    val SecondaryLabelDark = Color(0x99EBEBF5) // #EBEBF5 @ 60%
    val TertiaryLabel = Color(0x4D3C3C43) // #3C3C43 @ 30%
    val TertiaryLabelDark = Color(0x4DEBEBF5) // #EBEBF5 @ 30%
}

/**
 * One appearance of the palette — everything a screen needs, already resolved
 * for light or dark. Read it through [IosPalette].
 */
@Immutable
data class IosColorScheme(
    val isDark: Boolean,
    val blue: Color,
    val green: Color,
    val red: Color,
    val orange: Color,
    val gray: Color,
    val gray2: Color,
    val gray3: Color,
    val gray4: Color,
    val gray5: Color,
    val gray6: Color,
    /** The page behind everything. iOS never puts a card on white. */
    val groupedBackground: Color,
    /** The surface of a list section, a row or a field. Flat — no elevation. */
    val secondaryGroupedBackground: Color,
    val separator: Color,
    val label: Color,
    val secondaryLabel: Color,
    val tertiaryLabel: Color,
    /** What a row turns while a finger is on it, in place of a ripple. */
    val pressedHighlight: Color,
)

val IosLightColors = IosColorScheme(
    isDark = false,
    blue = IosColors.SystemBlue,
    green = IosColors.SystemGreen,
    red = IosColors.SystemRed,
    orange = IosColors.SystemOrange,
    gray = IosColors.SystemGray,
    gray2 = IosColors.SystemGray2,
    gray3 = IosColors.SystemGray3,
    gray4 = IosColors.SystemGray4,
    gray5 = IosColors.SystemGray5,
    gray6 = IosColors.SystemGray6,
    groupedBackground = IosColors.GroupedBackground,
    secondaryGroupedBackground = IosColors.SecondaryGroupedBackground,
    separator = IosColors.Separator,
    label = IosColors.Label,
    secondaryLabel = IosColors.SecondaryLabel,
    tertiaryLabel = IosColors.TertiaryLabel,
    pressedHighlight = IosColors.SystemGray4,
)

val IosDarkColors = IosColorScheme(
    isDark = true,
    blue = IosColors.SystemBlueDark,
    green = IosColors.SystemGreenDark,
    red = IosColors.SystemRedDark,
    orange = IosColors.SystemOrangeDark,
    gray = IosColors.SystemGray,
    gray2 = IosColors.SystemGray2Dark,
    gray3 = IosColors.SystemGray3Dark,
    gray4 = IosColors.SystemGray4Dark,
    gray5 = IosColors.SystemGray5Dark,
    gray6 = IosColors.SystemGray6Dark,
    groupedBackground = IosColors.GroupedBackgroundDark,
    secondaryGroupedBackground = IosColors.SecondaryGroupedBackgroundDark,
    separator = IosColors.SeparatorDark,
    label = IosColors.LabelDark,
    secondaryLabel = IosColors.SecondaryLabelDark,
    tertiaryLabel = IosColors.TertiaryLabelDark,
    pressedHighlight = IosColors.SystemGray5Dark,
)

/**
 * The palette for the current appearance.
 *
 * Deliberately a plain composable read of [isSystemInDarkTheme] rather than a
 * CompositionLocal: there is one palette, it is never overridden per subtree,
 * and a local that can be overridden is a local somebody will override for one
 * screen.
 */
val IosPalette: IosColorScheme
    @Composable get() = if (isSystemInDarkTheme()) IosDarkColors else IosLightColors
