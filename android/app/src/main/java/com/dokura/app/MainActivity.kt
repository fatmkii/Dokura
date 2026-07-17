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
    primary = Color(0xFF315C4B),
    onPrimary = Color(0xFFFFFFFF),
    secondary = Color(0xFF9A5A38),
    background = Color(0xFFF5F1E8),
    surface = Color(0xFFFCF9F2),
    surfaceVariant = Color(0xFFE7E0D3),
    onBackground = Color(0xFF202723),
    outline = Color(0xFF817B70),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFA9CDBB),
    onPrimary = Color(0xFF113729),
    secondary = Color(0xFFFFB68F),
    background = Color(0xFF121916),
    surface = Color(0xFF18211D),
    surfaceVariant = Color(0xFF29332E),
    onBackground = Color(0xFFE4E9E3),
    outline = Color(0xFF8D9991),
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
