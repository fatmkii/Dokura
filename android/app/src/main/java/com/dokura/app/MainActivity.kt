package com.dokura.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { DokuraApp() }
    }
}

private val DokuraColors = darkColorScheme(
    primary = Color(0xFFA9C09D),
    background = Color(0xFF18201D),
    surface = Color(0xFF18201D),
    onBackground = Color(0xFFF0EEE6),
)

@Composable
fun DokuraApp() {
    MaterialTheme(colorScheme = DokuraColors) {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background),
        ) {
            Column(
                modifier = Modifier.padding(horizontal = 28.dp, vertical = 52.dp),
                verticalArrangement = Arrangement.Center,
            ) {
                Text(
                    text = stringResource(R.string.welcome_eyebrow),
                    color = MaterialTheme.colorScheme.primary,
                    fontSize = 12.sp,
                    letterSpacing = 2.sp,
                )
                Text(
                    text = stringResource(R.string.welcome_title),
                    modifier = Modifier.padding(top = 22.dp),
                    fontFamily = FontFamily.Serif,
                    fontWeight = FontWeight.Medium,
                    fontSize = 42.sp,
                    lineHeight = 50.sp,
                )
                Text(
                    text = stringResource(R.string.welcome_body),
                    modifier = Modifier.padding(top = 22.dp),
                    color = Color(0xFFA9AAA1),
                    fontSize = 15.sp,
                    lineHeight = 25.sp,
                )
                Text(
                    text = stringResource(R.string.stage_label),
                    modifier = Modifier.padding(top = 34.dp),
                    color = Color(0xFF717A74),
                    fontSize = 11.sp,
                    letterSpacing = 1.sp,
                )
            }
        }
    }
}
