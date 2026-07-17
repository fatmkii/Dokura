package com.dokura.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.dokura.app.DokuraViewModel
import com.dokura.app.UiText
import com.dokura.app.data.ConnectionSettings
import com.dokura.app.data.ThemeMode
import com.dokura.app.network.ConnectionTestResult

@Composable
fun SettingsScreen(viewModel: DokuraViewModel) {
    val settings by viewModel.settings.collectAsState()
    val result by viewModel.connectionTest.collectAsState()
    var address by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("8000") }
    var apiKey by remember { mutableStateOf("") }
    LaunchedEffect(settings.connection) {
        address = settings.connection.address
        port = settings.connection.port.toString()
    }
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(UiText.Settings, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
        SettingsSection(UiText.Connection) {
            OutlinedTextField(address, { address = it; viewModel.clearConnectionResult() }, Modifier.fillMaxWidth().testTag("serverAddress"), label = { Text(UiText.ServerAddress) }, singleLine = true)
            OutlinedTextField(
                port,
                { port = it.filter(Char::isDigit); viewModel.clearConnectionResult() },
                Modifier.fillMaxWidth().testTag("serverPort"),
                label = { Text(UiText.Port) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            )
            OutlinedTextField(
                apiKey,
                { apiKey = it; viewModel.clearConnectionResult() },
                Modifier.fillMaxWidth().testTag("apiKey"),
                label = { Text(if (viewModel.apiKeyConfigured) "${UiText.ApiKey}（已安全保存，留空不修改）" else UiText.ApiKey) },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val connection = { ConnectionSettings(address.trim(), port.toIntOrNull() ?: 0) }
                TextButton(onClick = { viewModel.testConnection(connection(), apiKey) }) { Text(UiText.TestConnection) }
                Button(onClick = { viewModel.saveConnection(connection(), apiKey); apiKey = "" }) { Text(UiText.Save) }
            }
            result?.let { ConnectionResult(it) }
        }
        SettingsSection(UiText.Appearance) {
            Text(UiText.Theme, fontWeight = FontWeight.Medium)
            ChoiceRow(
                options = listOf(ThemeMode.SYSTEM to UiText.SystemTheme, ThemeMode.LIGHT to UiText.LightTheme, ThemeMode.DARK to UiText.DarkTheme),
                selected = settings.theme,
                onSelect = viewModel::setTheme,
            )
        }
        SettingsSection(UiText.Reading) {
            Text(UiText.PreviewColumns, fontWeight = FontWeight.Medium)
            ChoiceRow(listOf(4 to "4 列", 5 to "5 列", 6 to "6 列"), settings.previewColumns, viewModel::setPreviewColumns)
            Text(UiText.CoverWidth, fontWeight = FontWeight.Medium)
            ChoiceRow(listOf(20 to "20%", 30 to "30%", 40 to "40%"), settings.coverWidthPercent, viewModel::setCoverWidth)
        }
        Text("Dokura 0.1.0 · API v1", color = MaterialTheme.colorScheme.outline, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun SettingsSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Surface(shape = MaterialTheme.shapes.large, tonalElevation = 1.dp) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold)
            content()
        }
    }
}

@Composable
private fun <T> ChoiceRow(options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit) {
    Row(Modifier.fillMaxWidth()) {
        options.forEach { (value, label) ->
            TextButton(onClick = { onSelect(value) }, Modifier.weight(1f).testTag("choice:$label")) {
                Text(if (selected == value) "• $label" else label)
            }
        }
    }
}

@Composable
private fun ConnectionResult(result: ConnectionTestResult) {
    val message = when (result) {
        is ConnectionTestResult.Success -> "连接成功 · 服务端 ${result.serverVersion}"
        ConnectionTestResult.InvalidAddress -> "地址或端口格式无效"
        ConnectionTestResult.TimedOut -> "连接超时（10 秒）"
        ConnectionTestResult.NotDokura -> "目标不是 Dokura 服务"
        ConnectionTestResult.InvalidApiKey -> "APIkey 无效"
        is ConnectionTestResult.IncompatibleVersion -> "API 版本不兼容（服务端 ${result.version}）"
        ConnectionTestResult.Unreachable -> "无法连接服务端"
    }
    Text(
        message,
        color = if (result is ConnectionTestResult.Success) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
        style = MaterialTheme.typography.bodyMedium,
    )
}
