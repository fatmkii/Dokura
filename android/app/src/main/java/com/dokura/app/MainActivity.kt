package com.dokura.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.graphics.Color
import com.dokura.app.data.ThemeMode
import com.dokura.app.ui.DokuraNavigation

class MainActivity : ComponentActivity() {
    private val viewModel: DokuraViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { DokuraApp(viewModel) }
    }

    override fun onStop() {
        viewModel.appBackgrounded()
        super.onStop()
    }

    override fun onTrimMemory(level: Int) {
        if (level >= TRIM_MEMORY_RUNNING_LOW) viewModel.onMemoryPressure()
        super.onTrimMemory(level)
    }
}

private val LightColors = lightColorScheme(
    primary = Color(0xFF7A2E2A),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFE8C7BE),
    onPrimaryContainer = Color(0xFF2E0806),
    inversePrimary = Color(0xFFFFB4AA),
    secondary = Color(0xFF8D4935),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFFFDCCB),
    onSecondaryContainer = Color(0xFF351009),
    tertiary = Color(0xFF7B5732),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFFFDDB6),
    onTertiaryContainer = Color(0xFF2B1700),
    background = Color(0xFFE2E0D2),
    onBackground = Color(0xFF302623),
    surface = Color(0xFFF2F0E5),
    onSurface = Color(0xFF302623),
    surfaceVariant = Color(0xFFEDEBE0),
    onSurfaceVariant = Color(0xFF554A44),
    surfaceTint = Color(0xFF7A2E2A),
    inverseSurface = Color(0xFF352F2C),
    inverseOnSurface = Color(0xFFF9EEE9),
    outline = Color(0xFF766B64),
    outlineVariant = Color(0xFFC7C1B6),
    scrim = Color(0xFF000000),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFFFB686),
    onPrimary = Color(0xFF4C260E),
    primaryContainer = Color(0xFF6B3A20),
    onPrimaryContainer = Color(0xFFFFE0CC),
    inversePrimary = Color(0xFF7A2E2A),
    secondary = Color(0xFFE0A08B),
    onSecondary = Color(0xFF48261D),
    secondaryContainer = Color(0xFF633A2E),
    onSecondaryContainer = Color(0xFFFFDCD1),
    tertiary = Color(0xFFE8C08B),
    onTertiary = Color(0xFF432C08),
    tertiaryContainer = Color(0xFF5D421E),
    onTertiaryContainer = Color(0xFFFFDEAD),
    background = Color(0xFF34353A),
    onBackground = Color(0xFFF3EEE8),
    surface = Color(0xFF3D414A),
    onSurface = Color(0xFFF3EEE8),
    surfaceVariant = Color(0xFF50535A),
    onSurfaceVariant = Color(0xFFD2CEC7),
    surfaceTint = Color(0xFFFFB686),
    inverseSurface = Color(0xFFF3EEE8),
    inverseOnSurface = Color(0xFF34353A),
    outline = Color(0xFFA9A49C),
    outlineVariant = Color(0xFF686A70),
    scrim = Color(0xFF000000),
)

@Composable
fun DokuraApp(viewModel: DokuraViewModel) {
    val settings by viewModel.settings.collectAsState()
    val dark = when (settings.theme) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    MaterialTheme(colorScheme = if (dark) DarkColors else LightColors) {
        Surface { DokuraNavigation(viewModel) }
    }
}
