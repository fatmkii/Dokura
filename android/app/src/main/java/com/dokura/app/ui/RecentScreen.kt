package com.dokura.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.dokura.app.DokuraViewModel
import com.dokura.app.UiText

@Composable
fun RecentScreen(viewModel: DokuraViewModel, openDetail: (String) -> Unit) {
    val recent by viewModel.recent.collectAsState()
    Column(Modifier.fillMaxSize()) {
        Text(UiText.Recent, Modifier.padding(16.dp), style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
        if (recent.isEmpty()) EmptyState(UiText.EmptyRecent) else LazyColumn {
            items(recent, key = { it.fileId }) { item ->
                Row(Modifier.fillMaxWidth().clickable { openDetail(item.fileId) }.padding(16.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text(item.fileName, fontWeight = FontWeight.Medium)
                        Text(item.relativePath, color = MaterialTheme.colorScheme.outline, style = MaterialTheme.typography.bodySmall)
                    }
                    Text("第 ${item.page} 页")
                }
                HorizontalDivider()
            }
        }
    }
}
