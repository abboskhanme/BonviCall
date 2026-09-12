package uz.bonvi.call.ui.ios

import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * The iOS text styles, mapped onto Compose [TextStyle].
 *
 * These are San Francisco's sizes and weights on the platform default font.
 * The font itself is NOT bundled: San Francisco is licensed for Apple
 * platforms, and a lookalike downloaded from somewhere is both a licence
 * question and 300 KB on an APK that is side-loaded over an Uzbek mobile
 * connection (N33, N40). Roboto at iOS metrics reads as a clean system app;
 * Roboto at Material metrics reads as an Android app, and that difference is
 * mostly size, weight and letter spacing rather than the glyphs.
 *
 * Line heights are ~1.25x the font size, which is what stops a 17sp row of
 * Uzbek text — a language with longer words than English — from looking
 * cramped. The large styles carry iOS's slightly negative tracking.
 */
object IosType {

    private val Family = FontFamily.Default

    /** iOS `largeTitle` — the navigation-bar title of a scrolled-to-top screen. */
    val largeTitle = TextStyle(
        fontFamily = Family,
        fontSize = 34.sp,
        lineHeight = 41.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = (-0.4).sp,
    )

    /** iOS `title1`. */
    val title1 = TextStyle(
        fontFamily = Family,
        fontSize = 28.sp,
        lineHeight = 34.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = (-0.4).sp,
    )

    /** iOS `title2`. */
    val title2 = TextStyle(
        fontFamily = Family,
        fontSize = 22.sp,
        lineHeight = 28.sp,
        fontWeight = FontWeight.Bold,
        letterSpacing = (-0.4).sp,
    )

    /** iOS `title3`. */
    val title3 = TextStyle(
        fontFamily = Family,
        fontSize = 20.sp,
        lineHeight = 25.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = (-0.4).sp,
    )

    /** iOS `headline` — a row title that needs emphasis, a button label. */
    val headline = TextStyle(
        fontFamily = Family,
        fontSize = 17.sp,
        lineHeight = 22.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = (-0.2).sp,
    )

    /** iOS `body` — the default. Every list row title is this size. */
    val body = TextStyle(
        fontFamily = Family,
        fontSize = 17.sp,
        lineHeight = 22.sp,
        fontWeight = FontWeight.Normal,
        letterSpacing = (-0.2).sp,
    )

    /** iOS `callout`. */
    val callout = TextStyle(
        fontFamily = Family,
        fontSize = 16.sp,
        lineHeight = 21.sp,
        fontWeight = FontWeight.Normal,
    )

    /** iOS `subhead` — the grey explanatory line under a title. */
    val subhead = TextStyle(
        fontFamily = Family,
        fontSize = 15.sp,
        lineHeight = 20.sp,
        fontWeight = FontWeight.Normal,
    )

    /** iOS `footnote` — section headers and footers. */
    val footnote = TextStyle(
        fontFamily = Family,
        fontSize = 13.sp,
        lineHeight = 18.sp,
        fontWeight = FontWeight.Normal,
    )

    /** iOS `caption1` — the smallest text that may carry meaning. */
    val caption = TextStyle(
        fontFamily = Family,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        fontWeight = FontWeight.Normal,
    )
}
