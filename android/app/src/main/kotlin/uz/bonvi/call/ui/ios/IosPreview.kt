package uz.bonvi.call.ui.ios

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

/**
 * Previews for the whole iOS design system.
 *
 * Every preview is deliberately NOT wrapped in `BonviCallTheme`: these
 * components read [IosPalette], not `MaterialTheme.colorScheme`, and a preview
 * that went through the app theme would hide the day one of them accidentally
 * started depending on it. The bare `MaterialTheme` is only there to give the
 * Material internals (the progress indicator, text selection) their defaults.
 *
 * The Uzbek strings below are SAMPLE DATA for the preview, not UI strings. Real
 * screens pass `stringResource(...)` — nothing in this package ships text.
 */

private const val SampleNumber = "+998 90 123 45 67"

@Composable
private fun PreviewHost(content: @Composable () -> Unit) {
    MaterialTheme { content() }
}

/** A padded grey page for previewing a single component out of context. */
@Composable
private fun PreviewPage(content: @Composable () -> Unit) {
    PreviewHost {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(IosPalette.groupedBackground)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            content()
        }
    }
}

// ── The whole screen, light and dark ──────────────────────────────────────

@Preview(name = "Screen — light", showBackground = true, heightDp = 900)
@Composable
private fun IosScreenPreview() {
    PreviewHost { SampleScreen() }
}

@Preview(
    name = "Screen — dark",
    showBackground = true,
    heightDp = 900,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun IosScreenDarkPreview() {
    PreviewHost { SampleScreen() }
}

@Composable
private fun SampleScreen() {
    IosScreen(
        title = "BonviCall",
        subtitle = "Qo'ng'iroqlaringiz yozib olinmoqda",
    ) {
        IosBigStatus(
            title = "Qayd etilmoqda",
            detail = "Xizmat ishlayapti. Yuborilmagan qo'ng'iroqlar: 2",
            tone = IosTone.Good,
        )

        IosSection(header = "Qurilma", footer = "Bu raqam admin panelida ko'rinadi.") {
            IosRow(title = "Raqam", value = SampleNumber)
            IosDivider()
            IosRow(title = "Xodim", value = "Aziz Karimov")
            IosDivider()
            IosRow(
                title = "Holat",
                trailing = { IosStatusBadge(text = "Faol", tone = IosTone.Good) },
            )
        }

        IosSection(header = "Navbat") {
            IosRow(
                title = "Mening qo'ng'iroqlarim",
                subtitle = "Oxirgi 7 kun",
                value = "24",
                showChevron = true,
                onClick = {},
            )
            IosDivider()
            IosRow(
                title = "Holat va diagnostika",
                showChevron = true,
                onClick = {},
            )
            IosDivider()
            IosRow(
                title = "Yuborilmagan",
                value = "2",
                trailing = { IosStatusBadge(text = "Kutilmoqda", tone = IosTone.Warn) },
            )
        }

        IosButton(text = "Yangilash", onClick = {})
        IosButton(text = "Yordam kerak", onClick = {}, style = IosButtonStyle.Tinted)
    }
}

@Preview(name = "Screen — back row", showBackground = true, heightDp = 500)
@Composable
private fun IosScreenBackPreview() {
    PreviewHost {
        IosScreen(
            title = "Diagnostika",
            onBack = {},
            backLabel = "Orqaga",
        ) {
            IosSection(footer = "Adminning so'roviga ko'ra shu sahifani o'qib bering.") {
                IosRow(title = "Ilova versiyasi", value = "1.0.0")
                IosDivider()
                IosRow(title = "Server", value = "bonvicall.uz")
            }
        }
    }
}

// ── Individual components ────────────────────────────────────────────────

@Preview(name = "Section + rows", showBackground = true)
@Composable
private fun IosSectionPreview() {
    PreviewPage {
        IosSection(header = "Ruxsatlar", footer = "Uchtasi ham kerak, aks holda yozib olinmaydi.") {
            IosRow(title = "Mikrofon", trailing = { IosStatusBadge("Berilgan", IosTone.Good) })
            IosDivider()
            IosRow(title = "Qo'ng'iroqlar tarixi", trailing = { IosStatusBadge("Berilgan", IosTone.Good) })
            IosDivider()
            IosRow(
                title = "Xotira",
                subtitle = "Sozlamalarda qo'lda yoqiladi",
                trailing = { IosStatusBadge("Yo'q", IosTone.Bad) },
                showChevron = true,
                onClick = {},
            )
        }
        IosSection {
            IosRow(title = "Faqat sarlavha")
            IosDivider()
            IosRow(title = "Qiymat bilan", value = "12")
        }
    }
}

@Preview(name = "Buttons", showBackground = true)
@Composable
private fun IosButtonPreview() {
    PreviewPage {
        IosButton(text = "Davom etish", onClick = {})
        IosButton(text = "Keyinroq", onClick = {}, style = IosButtonStyle.Tinted)
        IosButton(text = "Yordam kerak", onClick = {}, style = IosButtonStyle.Plain)
        IosButton(text = "Qayta ro'yxatdan o'tish", onClick = {}, style = IosButtonStyle.Destructive)
        IosButton(text = "Davom etish", onClick = {}, enabled = false)
        IosButton(text = "Keyinroq", onClick = {}, enabled = false, style = IosButtonStyle.Tinted)
    }
}

@Preview(
    name = "Buttons — dark",
    showBackground = true,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun IosButtonDarkPreview() {
    PreviewPage {
        IosButton(text = "Davom etish", onClick = {})
        IosButton(text = "Keyinroq", onClick = {}, style = IosButtonStyle.Tinted)
        IosButton(text = "Yordam kerak", onClick = {}, style = IosButtonStyle.Plain)
        IosButton(text = "Qayta ro'yxatdan o'tish", onClick = {}, style = IosButtonStyle.Destructive)
        IosButton(text = "Davom etish", onClick = {}, enabled = false)
    }
}

@Preview(name = "Text fields", showBackground = true)
@Composable
private fun IosTextFieldPreview() {
    PreviewPage {
        var code by remember { mutableStateOf("") }
        var number by remember { mutableStateOf(SampleNumber) }
        var secret by remember { mutableStateOf("parol123") }

        IosTextField(
            value = code,
            onValueChange = { code = it },
            placeholder = "8 ta belgi",
            label = "Ro'yxatdan o'tish kodi",
            keyboardType = KeyboardType.Text,
        )
        IosTextField(
            value = number,
            onValueChange = { number = it },
            placeholder = "+998 __ ___ __ __",
            label = "Telefon raqami",
            keyboardType = KeyboardType.Phone,
        )
        IosTextField(
            value = secret,
            onValueChange = { secret = it },
            placeholder = "Parol",
            isPassword = true,
            keyboardType = KeyboardType.Password,
        )
    }
}

@Preview(name = "Badges", showBackground = true)
@Composable
private fun IosStatusBadgePreview() {
    PreviewPage {
        IosSection(header = "Holatlar") {
            IosRow(title = "Yozib olinmoqda", trailing = { IosStatusBadge("Faol", IosTone.Good) })
            IosDivider()
            IosRow(title = "Navbat", trailing = { IosStatusBadge("Kutilmoqda", IosTone.Warn) })
            IosDivider()
            IosRow(title = "Xizmat", trailing = { IosStatusBadge("O'chiq", IosTone.Bad) })
            IosDivider()
            IosRow(title = "Noma'lum", trailing = { IosStatusBadge("Tekshirilmagan", IosTone.Neutral) })
        }
    }
}

@Preview(name = "Big status", showBackground = true)
@Composable
private fun IosBigStatusPreview() {
    PreviewPage {
        IosBigStatus(
            title = "Qayd etilmoqda",
            detail = "Hammasi joyida. Hech narsa talab qilinmaydi.",
            tone = IosTone.Good,
        )
        IosBigStatus(
            title = "Yozib olinmayapti",
            detail = "Xotiraga ruxsat berilmagan. Sozlamalarni oching.",
            tone = IosTone.Bad,
        )
        IosBigStatus(title = "Tekshirilmoqda", detail = null, tone = IosTone.Neutral)
    }
}

@Preview(
    name = "Big status — dark",
    showBackground = true,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun IosBigStatusDarkPreview() {
    PreviewPage {
        IosBigStatus(
            title = "Qayd etilmoqda",
            detail = "Hammasi joyida. Hech narsa talab qilinmaydi.",
            tone = IosTone.Good,
        )
        IosBigStatus(
            title = "Kutilmoqda",
            detail = "2 ta qo'ng'iroq yuborilmagan.",
            tone = IosTone.Warn,
        )
    }
}

@Preview(name = "Loading", showBackground = true)
@Composable
private fun IosLoadingPreview() {
    PreviewPage {
        IosSection(header = "Yuklanmoqda") {
            IosLoading()
        }
    }
}

@Preview(name = "Typography", showBackground = true)
@Composable
private fun IosTypePreview() {
    PreviewPage {
        val palette = IosPalette
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("largeTitle 34", style = IosType.largeTitle, color = palette.label)
            Text("title1 28", style = IosType.title1, color = palette.label)
            Text("title2 22", style = IosType.title2, color = palette.label)
            Text("title3 20", style = IosType.title3, color = palette.label)
            Text("headline 17", style = IosType.headline, color = palette.label)
            Text("body 17 — qo'ng'iroq yozib olinmoqda", style = IosType.body, color = palette.label)
            Text("callout 16", style = IosType.callout, color = palette.label)
            Text("subhead 15", style = IosType.subhead, color = palette.secondaryLabel)
            Text("footnote 13", style = IosType.footnote, color = palette.secondaryLabel)
            Text("caption 12", style = IosType.caption, color = palette.tertiaryLabel)
        }
    }
}
