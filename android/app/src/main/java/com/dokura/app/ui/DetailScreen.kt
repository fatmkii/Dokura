package com.dokura.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import com.dokura.app.DokuraViewModel
import com.dokura.app.UiText
import com.dokura.app.data.FileDetailDto
import java.text.DateFormat
import java.util.Date

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(viewModel: DokuraViewModel, id: String, onBack: () -> Unit) {
    val state by viewModel.detail.collectAsState()
    val settings by viewModel.settings.collectAsState()
    LaunchedEffect(id) { viewModel.detailVisible(); viewModel.loadDetail(id) }
    DisposableEffect(id) { onDispose { viewModel.closeDetail() } }
    Scaffold(topBar = {
        TopAppBar(
            title = { Text(state.item?.name ?: "文件详情", maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = { TextButton(onClick = onBack) { Text("返回") } },
        )
    }) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                state.loading -> LoadingState()
                state.item == null && state.error != null -> ErrorState(state.error!!, { viewModel.loadDetail(id) })
                state.item != null -> DetailContent(
                    item = state.item!!,
                    columns = settings.previewColumns,
                    headers = viewModel.imageHeaders(),
                    imageUrl = viewModel::imageUrl,
                    savingRating = state.savingRating,
                    error = state.error,
                    onRating = viewModel::setRating,
                    onColumns = viewModel::setPreviewColumns,
                )
            }
        }
    }
}

@Composable
private fun DetailContent(
    item: FileDetailDto,
    columns: Int,
    headers: Map<String, String>,
    imageUrl: (String) -> String?,
    savingRating: Boolean,
    error: String?,
    onRating: (Int) -> Unit,
    onColumns: (Int) -> Unit,
) {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val landscape = maxWidth > maxHeight
        val containerWidth = maxWidth
        val density = LocalDensity.current
        if (landscape) {
            Row(Modifier.fillMaxSize()) {
                Column(Modifier.width(containerWidth * .38f).verticalScroll(rememberScrollState()).padding(16.dp)) {
                    Hero(item, headers, imageUrl, savingRating, error, onRating)
                    Metadata(item)
                }
                val previewSize = previewTier(with(density) { ((containerWidth * .62f) / columns).toPx() })
                PreviewGrid(item, columns, previewSize, headers, imageUrl, onColumns, Modifier.weight(1f))
            }
        } else {
            val previewSize = previewTier(with(density) { (containerWidth / columns).toPx() })
            val gridState = rememberLazyGridState()
            LazyVerticalGrid(columns = GridCells.Fixed(columns), state = gridState, modifier = Modifier.fillMaxSize()) {
                item(span = { GridItemSpan(maxLineSpan) }) { Hero(item, headers, imageUrl, savingRating, error, onRating) }
                item(span = { GridItemSpan(maxLineSpan) }) { Metadata(item) }
                item(span = { GridItemSpan(maxLineSpan) }) { PreviewHeader(columns, onColumns) }
                items(item.pages, key = { it.number }) { page ->
                    PreviewCell(item, page, previewSize, headers, imageUrl)
                }
            }
        }
    }
}

@Composable
private fun Hero(
    item: FileDetailDto,
    headers: Map<String, String>,
    imageUrl: (String) -> String?,
    savingRating: Boolean,
    error: String?,
    onRating: (Int) -> Unit,
) {
    Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.Top) {
        RemoteImage(
            url = imageUrl("api/v1/files/${item.id}/cover"),
            headers = headers,
            description = item.name,
            modifier = Modifier.fillMaxWidth(.4f).aspectRatio(.72f),
        )
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(item.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text(tagSummary(item), color = MaterialTheme.colorScheme.outline, style = MaterialTheme.typography.bodySmall)
            Row {
                (0..5).forEach { value ->
                    TextButton(onClick = { onRating(value) }, enabled = !savingRating) {
                        Text(if (value == 0) "清除" else if (value <= item.rating) "★" else "☆")
                    }
                }
            }
            Button(onClick = {}, enabled = false) { Text(UiText.StartReading) }
            if (error != null) Text(error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun Metadata(item: FileDetailDto) {
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(UiText.Metadata, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        MetadataRow("路径", item.relativePath)
        MetadataRow("文件大小", readableBytes(item.size))
        MetadataRow("修改时间", DateFormat.getDateTimeInstance().format(Date(item.modifiedNs / 1_000_000)))
        MetadataRow("页数", "${item.pageCount}（不可用 ${item.unavailablePageCount}）")
        MetadataRow("处理状态", UiText.statusLabel(item.status))
        MetadataRow("未分类 tag", item.unclassifiedTags.joinToString("、").ifBlank { UiText.Unrecognized })
        MetadataRow("错误原因", item.lastError ?: UiText.Unrecognized)
    }
}

@Composable
private fun MetadataRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth()) {
        Text(label, Modifier.width(88.dp), color = MaterialTheme.colorScheme.outline)
        Text(value, Modifier.weight(1f))
    }
    HorizontalDivider()
}

@Composable
private fun PreviewGrid(
    item: FileDetailDto,
    columns: Int,
    previewSize: Int,
    headers: Map<String, String>,
    imageUrl: (String) -> String?,
    onColumns: (Int) -> Unit,
    modifier: Modifier,
) {
    Column(modifier.padding(12.dp)) {
        PreviewHeader(columns, onColumns)
        LazyVerticalGrid(columns = GridCells.Fixed(columns), modifier = Modifier.weight(1f), userScrollEnabled = true) {
            items(item.pages, key = { it.number }) { page ->
                PreviewCell(item, page, previewSize, headers, imageUrl)
            }
        }
    }
}

@Composable
private fun PreviewHeader(columns: Int, onColumns: (Int) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(UiText.ContentPreview, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        listOf(4, 5, 6).forEach { value ->
            TextButton(onClick = { onColumns(value) }) { Text(if (columns == value) "• $value 列" else "$value") }
        }
    }
}

@Composable
private fun PreviewCell(
    item: FileDetailDto,
    page: com.dokura.app.data.PageDto,
    previewSize: Int,
    headers: Map<String, String>,
    imageUrl: (String) -> String?,
) {
    Column(Modifier.padding(3.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        if (page.unavailable) {
            Box(Modifier.fillMaxWidth().aspectRatio(.72f), contentAlignment = Alignment.Center) { Text("页面不可用", style = MaterialTheme.typography.labelSmall) }
        } else {
            RemoteImage(
                url = imageUrl("api/v1/files/${item.id}/pages/${page.number}/preview?size=$previewSize&purpose=preview"),
                headers = headers,
                description = "第 ${page.number} 页",
                modifier = Modifier.fillMaxWidth().aspectRatio(.72f),
            )
        }
        Text("${page.number}", style = MaterialTheme.typography.labelSmall)
    }
}

internal fun previewTier(physicalPixels: Float): Int = when {
    physicalPixels <= 256 -> 256
    physicalPixels <= 512 -> 512
    else -> 768
}

private fun tagSummary(item: FileDetailDto): String = item.tags
    .filter { it.category in setOf("author", "original", "language") }
    .joinToString(" · ") { it.value }
    .ifBlank { UiText.Unrecognized }

private fun readableBytes(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val units = listOf("KB", "MB", "GB", "TB")
    var value = bytes.toDouble()
    var index = -1
    while (value >= 1024 && index < units.lastIndex) { value /= 1024; index++ }
    return "%.1f %s".format(value, units[index])
}
