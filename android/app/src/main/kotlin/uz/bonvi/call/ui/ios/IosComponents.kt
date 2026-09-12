package uz.bonvi.call.ui.ios

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * The iOS design system for this app.
 *
 * Material3 is what draws — it is the dependency the project already has — but
 * nothing here is allowed to LOOK Material. No elevation (iOS puts flat white
 * cards on a grey page, and a shadow is the single fastest way to give the
 * game away), no ripple (rows dim, they do not spread ink), no text-field
 * underline, no pill-shaped tonal buttons.
 *
 * Every user-facing string is a parameter. The app is Uzbek-only and the
 * catalogue lives in `res/values/strings.xml`; a design-system file that
 * hardcoded one word of Uzbek would be a second catalogue.
 */

// ─────────────────────────────────────────────────────────────────────────
// Shared vocabulary
// ─────────────────────────────────────────────────────────────────────────

/** The four button appearances iOS actually uses in a form. */
enum class IosButtonStyle { Filled, Tinted, Plain, Destructive }

/**
 * What a piece of status means, not what colour it is.
 *
 * Callers say `Bad`, never "red" — so the day dark mode changes systemRed the
 * screens do not have to be found and edited.
 */
enum class IosTone { Good, Warn, Bad, Neutral }

/** The accent a [IosTone] resolves to in the current appearance. */
fun IosTone.color(palette: IosColorScheme): Color = when (this) {
    IosTone.Good -> palette.green
    IosTone.Warn -> palette.orange
    IosTone.Bad -> palette.red
    IosTone.Neutral -> palette.gray
}

/** iOS tints a status background at ~15%; on black it needs a little more. */
private fun tintAlpha(palette: IosColorScheme): Float = if (palette.isDark) 0.24f else 0.15f

/** The corner radius of an inset-grouped card and of a text field. */
private val CardCorner = RoundedCornerShape(10.dp)

/** The minimum height of a list row on iOS. Nothing smaller is comfortably
 *  tappable on a phone held in one hand on a bus. */
private val RowMinHeight = 44.dp

/** The page gutter. Every inset-grouped card sits this far from the edge. */
private val ScreenPadding = 16.dp

/** U+203A / U+2039. The row disclosure and the back chevron. Glyphs rather
 *  than Material icons: `KeyboardArrowRight` is twice as heavy as iOS's and is
 *  instantly recognisable as Android. */
private const val ChevronRight = "›"
private const val ChevronLeft = "‹"

/** A clickable that shows no ripple. Press feedback is the caller's job —
 *  a dimmed row or a dimmed button, the way iOS does it. */
@Composable
private fun Modifier.pressable(
    interactionSource: MutableInteractionSource,
    enabled: Boolean,
    onClick: (() -> Unit)?,
): Modifier = if (onClick == null) {
    this
} else {
    clickable(
        interactionSource = interactionSource,
        indication = null,
        enabled = enabled,
        onClick = onClick,
    )
}

// ─────────────────────────────────────────────────────────────────────────
// Screen
// ─────────────────────────────────────────────────────────────────────────

/**
 * Imitates an iOS **large-title screen** — Settings.app's root, or any
 * `UINavigationController` with `prefersLargeTitles`.
 *
 * Grey grouped page, a 34sp left-aligned title, an optional back row with the
 * "<" chevron above it, and a scrolling body inset 16dp from both edges.
 *
 * The title does not shrink into a navigation bar on scroll. That transition is
 * the one genuinely expensive piece of the iOS look, it needs a nested-scroll
 * connection per screen, and on a phone whose owner will spend eight seconds a
 * day in this app it buys nothing.
 *
 * @param backLabel the word next to the back chevron, e.g. "Orqaga". Null shows
 *   the chevron alone. Like every other string here it comes from the caller.
 */
@Composable
fun IosScreen(
    title: String,
    subtitle: String? = null,
    onBack: (() -> Unit)? = null,
    backLabel: String? = null,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val palette = IosPalette
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(palette.groupedBackground),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(bottom = 32.dp),
        ) {
            if (onBack != null) {
                IosBackRow(label = backLabel, onBack = onBack)
            }

            Text(
                text = title,
                style = IosType.largeTitle,
                color = palette.label,
                modifier = Modifier.padding(
                    start = ScreenPadding,
                    end = ScreenPadding,
                    top = if (onBack != null) 4.dp else 20.dp,
                ),
            )

            if (subtitle != null) {
                Text(
                    text = subtitle,
                    style = IosType.subhead,
                    color = palette.secondaryLabel,
                    modifier = Modifier.padding(
                        start = ScreenPadding,
                        end = ScreenPadding,
                        top = 4.dp,
                    ),
                )
            }

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = ScreenPadding, end = ScreenPadding, top = 20.dp),
                verticalArrangement = Arrangement.spacedBy(20.dp),
                content = content,
            )
        }
    }
}

/** The back affordance of an iOS navigation bar: a thin chevron and a word,
 *  both in the tint colour, both one tap target. */
@Composable
private fun IosBackRow(label: String?, onBack: () -> Unit) {
    val palette = IosPalette
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Row(
        modifier = Modifier
            .heightIn(min = RowMinHeight)
            .pressable(interaction, enabled = true, onClick = onBack)
            .padding(start = 12.dp, end = ScreenPadding)
            .alpha(if (pressed) 0.4f else 1f),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = ChevronLeft,
            style = IosType.title1.copy(fontWeight = FontWeight.Normal),
            color = palette.blue,
        )
        if (label != null) {
            Text(
                text = label,
                style = IosType.body,
                color = palette.blue,
                modifier = Modifier.padding(start = 6.dp),
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Inset grouped list
// ─────────────────────────────────────────────────────────────────────────

/**
 * Imitates an iOS **inset-grouped table section** (`UITableView.Style.insetGrouped`)
 * — the single element that makes a screen read as iOS.
 *
 * An uppercase grey footnote above, a flat rounded card holding the rows, a
 * grey footnote below. The footer is where iOS puts the sentence explaining
 * what the section does; using it is what keeps explanation out of the rows.
 *
 * Rows are separated by [IosDivider] placed between them by the caller, because
 * only the caller knows which rows are conditional — a divider inserted
 * automatically becomes a divider hanging under an empty section.
 */
@Composable
fun IosSection(
    header: String? = null,
    footer: String? = null,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val palette = IosPalette
    Column(modifier = modifier.fillMaxWidth()) {
        if (header != null) {
            Text(
                text = header.uppercase(),
                style = IosType.footnote,
                color = palette.secondaryLabel,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 7.dp),
            )
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(CardCorner)
                .background(palette.secondaryGroupedBackground),
            content = content,
        )

        if (footer != null) {
            Text(
                text = footer,
                style = IosType.footnote,
                color = palette.secondaryLabel,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 7.dp),
            )
        }
    }
}

/**
 * Imitates an iOS **table view cell**: 44dp minimum, title left, grey value
 * right, an optional disclosure chevron.
 *
 * Pressing dims the row instead of rippling. A ripple is Material's signature
 * gesture and survives every other change you make to a screen.
 */
@Composable
fun IosRow(
    title: String,
    subtitle: String? = null,
    value: String? = null,
    trailing: (@Composable () -> Unit)? = null,
    showChevron: Boolean = false,
    onClick: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val palette = IosPalette
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val background = if (pressed && onClick != null) palette.pressedHighlight else Color.Transparent

    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = RowMinHeight)
            .background(background)
            .pressable(interaction, enabled = true, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, style = IosType.body, color = palette.label)
            if (subtitle != null) {
                Text(
                    text = subtitle,
                    style = IosType.footnote,
                    color = palette.secondaryLabel,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }

        if (value != null) {
            Text(
                text = value,
                style = IosType.body,
                color = palette.secondaryLabel,
                textAlign = TextAlign.End,
                modifier = Modifier.padding(start = 8.dp),
            )
        }

        if (trailing != null) {
            Box(modifier = Modifier.padding(start = 8.dp)) { trailing() }
        }

        if (showChevron) {
            Text(
                text = ChevronRight,
                style = IosType.title3.copy(fontWeight = FontWeight.Medium),
                color = palette.gray3,
                modifier = Modifier.padding(start = 6.dp),
            )
        }
    }
}

/**
 * Imitates an iOS **cell separator**: a hairline inset to the left by the cell's
 * own margin, running full bleed to the right edge of the card.
 *
 * The inset is the tell. A full-width line is Material's `Divider`; the inset
 * one is what says the two rows belong to the same group.
 */
@Composable
fun IosDivider(modifier: Modifier = Modifier) {
    val palette = IosPalette
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 16.dp)
            .height(0.5.dp)
            .background(palette.separator),
    )
}

// ─────────────────────────────────────────────────────────────────────────
// Buttons
// ─────────────────────────────────────────────────────────────────────────

/**
 * Imitates an iOS 15+ **button configuration**: `filled`, `tinted`, `plain` and
 * the destructive role.
 *
 * `Destructive` is `Filled` in systemRed rather than red text on white: the
 * actions it guards here (re-enrol, which discards this installation) are the
 * ones that must not be tapped by accident, and a plate is harder to hit than
 * a line of text.
 *
 * Full width, 50dp, 12dp corners — the proportions of the primary button at the
 * bottom of an iOS onboarding sheet, which is exactly what the enrolment flow
 * is. Disabled is a grey plate rather than a faded blue one, because a faded
 * blue button on a slow phone looks like a button mid-tap.
 */
@Composable
fun IosButton(
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    style: IosButtonStyle = IosButtonStyle.Filled,
    modifier: Modifier = Modifier,
) {
    val palette = IosPalette
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()

    val container: Color = when {
        !enabled && style == IosButtonStyle.Plain -> Color.Transparent
        !enabled -> palette.gray5
        style == IosButtonStyle.Filled -> palette.blue
        style == IosButtonStyle.Destructive -> palette.red
        style == IosButtonStyle.Tinted -> palette.blue.copy(alpha = tintAlpha(palette))
        else -> Color.Transparent
    }
    val content: Color = when {
        !enabled -> palette.tertiaryLabel
        style == IosButtonStyle.Filled || style == IosButtonStyle.Destructive -> Color.White
        else -> palette.blue
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(50.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(container)
            .pressable(interaction, enabled = enabled, onClick = onClick)
            .alpha(if (pressed && enabled) 0.6f else 1f),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = text,
            style = IosType.headline,
            color = content,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 16.dp),
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Text field
// ─────────────────────────────────────────────────────────────────────────

/**
 * Imitates an iOS **grouped-list text field** — the cell you type the code into,
 * not a Material `TextField`.
 *
 * A flat white 44dp plate with 10dp corners, 17sp text, a grey placeholder that
 * simply disappears. No underline, no floating label, no counter: the three
 * things that make a Compose form look Android from across a room.
 *
 * Built on `BasicTextField` on purpose. Material's `TextField` cannot be talked
 * out of its container height and its label animation, and every attempt to do
 * it leaves one of them behind.
 */
@Composable
fun IosTextField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    label: String? = null,
    isPassword: Boolean = false,
    keyboardType: KeyboardType = KeyboardType.Text,
    modifier: Modifier = Modifier,
) {
    val palette = IosPalette
    Column(modifier = modifier.fillMaxWidth()) {
        if (label != null) {
            Text(
                text = label.uppercase(),
                style = IosType.footnote,
                color = palette.secondaryLabel,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 7.dp),
            )
        }

        BasicTextField(
            value = value,
            onValueChange = onValueChange,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = RowMinHeight)
                .clip(CardCorner)
                .background(palette.secondaryGroupedBackground),
            textStyle = IosType.body.copy(color = palette.label),
            singleLine = true,
            cursorBrush = SolidColor(palette.blue),
            visualTransformation = if (isPassword) {
                PasswordVisualTransformation()
            } else {
                VisualTransformation.None
            },
            keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
            decorationBox = { innerTextField ->
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = RowMinHeight)
                        .padding(horizontal = 16.dp),
                    contentAlignment = Alignment.CenterStart,
                ) {
                    if (value.isEmpty()) {
                        Text(
                            text = placeholder,
                            style = IosType.body,
                            color = palette.gray2,
                        )
                    }
                    innerTextField()
                }
            },
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Status
// ─────────────────────────────────────────────────────────────────────────

/**
 * Imitates the small tinted **capsule** iOS uses for a state word — the kind
 * that sits at the right end of a row.
 *
 * Tinted background, same-hue text, never a solid colour block: a solid red pill
 * on a white card is a Material chip.
 */
@Composable
fun IosStatusBadge(
    text: String,
    tone: IosTone,
    modifier: Modifier = Modifier,
) {
    val palette = IosPalette
    val accent = tone.color(palette)
    Box(
        modifier = modifier
            .clip(CircleShape)
            .background(accent.copy(alpha = tintAlpha(palette)))
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) {
        Text(
            text = text,
            style = IosType.footnote.copy(fontWeight = FontWeight.SemiBold),
            color = accent,
        )
    }
}

/**
 * Imitates the **hero status block** of an iOS utility app — Find My's "This
 * iPhone", the top of a VPN or Screen Time screen.
 *
 * A large tinted circle with a solid dot, a 22sp title, one grey line beneath.
 * It exists so the home screen answers "is it working?" from arm's length, which
 * is the only question the person carrying the phone actually has.
 */
@Composable
fun IosBigStatus(
    title: String,
    detail: String?,
    tone: IosTone,
    modifier: Modifier = Modifier,
) {
    val palette = IosPalette
    val accent = tone.color(palette)
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .size(76.dp)
                .clip(CircleShape)
                .background(accent.copy(alpha = tintAlpha(palette))),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape)
                    .background(accent),
            )
        }

        Text(
            text = title,
            style = IosType.title2.copy(fontWeight = FontWeight.SemiBold),
            color = palette.label,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 16.dp),
        )

        if (detail != null) {
            Text(
                text = detail,
                style = IosType.subhead,
                color = palette.secondaryLabel,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 6.dp, start = 24.dp, end = 24.dp),
            )
        }
    }
}

/**
 * Imitates the iOS **activity indicator**: small, grey, centred, no label.
 *
 * Grey rather than tinted on purpose — a blue spinner is a Material progress
 * indicator, and iOS only tints a spinner when it is inside a coloured bar.
 */
@Composable
fun IosLoading(modifier: Modifier = Modifier) {
    val palette = IosPalette
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 48.dp),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(28.dp),
            color = palette.gray,
            strokeWidth = 2.5.dp,
        )
    }
}
