package org.epiprot.phone.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** EpiProt colours: calm teal for "all is well", warm coral for alarms, soft neutral backgrounds. */
object EpiColors {
    val Teal = Color(0xFF0E7C86)
    val TealDark = Color(0xFF075E66)
    val TealSoft = Color(0xFFDDF1F1)
    val Mint = Color(0xFF2E9E6B)
    val MintSoft = Color(0xFFDFF3E8)
    val Coral = Color(0xFFD9483B)
    val CoralDark = Color(0xFFB0302A)
    val CoralSoft = Color(0xFFFBE3E0)
    val Amber = Color(0xFFC77700)
    val AmberSoft = Color(0xFFFFF0D6)
    val Ink = Color(0xFF1B2B2E)
    val InkSoft = Color(0xFF5B6B6E)
    val Line = Color(0xFFE3EAEA)
    val Background = Color(0xFFF4F8F8)
    val Card = Color.White
    val Grey = Color(0xFF9AA8AA)
    val GreySoft = Color(0xFFEDF1F1)
}

private val scheme = lightColorScheme(
    primary = EpiColors.Teal,
    onPrimary = Color.White,
    primaryContainer = EpiColors.TealSoft,
    onPrimaryContainer = EpiColors.TealDark,
    secondary = EpiColors.Mint,
    secondaryContainer = EpiColors.TealSoft,
    onSecondaryContainer = EpiColors.TealDark,
    error = EpiColors.Coral,
    background = EpiColors.Background,
    onBackground = EpiColors.Ink,
    surface = EpiColors.Card,
    onSurface = EpiColors.Ink,
    surfaceVariant = EpiColors.GreySoft,
    onSurfaceVariant = EpiColors.InkSoft,
    outline = EpiColors.Line,
    surfaceContainer = Color.White,
)

private val typography = Typography(
    headlineMedium = TextStyle(fontSize = 26.sp, fontWeight = FontWeight.Bold, lineHeight = 32.sp),
    titleLarge = TextStyle(fontSize = 21.sp, fontWeight = FontWeight.Bold, lineHeight = 27.sp),
    titleMedium = TextStyle(fontSize = 17.sp, fontWeight = FontWeight.SemiBold, lineHeight = 23.sp),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 17.sp),
    labelLarge = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.SemiBold),
)

private val shapes = Shapes(
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(20.dp),
    large = RoundedCornerShape(28.dp),
)

@Composable
fun EpiProtTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = scheme, typography = typography, shapes = shapes, content = content)
}
