package com.dokura.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.dokura.app.DokuraViewModel
import com.dokura.app.UiText
import com.dokura.app.data.CatalogItemDto
import com.dokura.app.data.TagCandidateDto
import kotlin.math.roundToInt
import kotlinx.coroutines.launch

@Composable
fun CatalogScreen(viewModel: DokuraViewModel, openDetail: (String) -> Unit) {
    val state by viewModel.catalog.collectAsState()
    val settings by viewModel.settings.collectAsState()
    val tags by viewModel.tags.collectAsState()
    val listState = rememberLazyListState()
    val coroutineScope = rememberCoroutineScope()
    var showFilters by remember { mutableStateOf(false) }
    DisposableEffect(Unit) {
        viewModel.catalogVisible()
        onDispose { viewModel.catalogHidden() }
    }
    LaunchedEffect(settings.connection, viewModel.apiKeyConfigured) {
        if (settings.connection.address.isNotBlank() && state.page == 0) viewModel.loadCatalog(reset = true)
    }
    val atEnd by remember {
        derivedStateOf {
            val last = listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
            last >= state.items.lastIndex - 4
        }
    }
    LaunchedEffect(atEnd) { if (atEnd && state.items.isNotEmpty()) viewModel.loadCatalog() }
    BackHandler(enabled = state.query.path.isNotEmpty()) {
        viewModel.leaveDirectory()?.let { index ->
            coroutineScope.launch { listState.scrollToItem(index) }
        }
    }

    Column(Modifier.fillMaxSize()) {
        CatalogHeader(
            path = state.query.path,
            search = state.query.search,
            onSearch = viewModel::search,
            onBreadcrumb = viewModel::navigateBreadcrumb,
            onFilters = { showFilters = true; viewModel.loadTags() },
            onRefresh = { viewModel.loadCatalog(reset = true) },
        )
        if (state.listChanged) {
            Surface(color = MaterialTheme.colorScheme.secondaryContainer) {
                Text(UiText.ListUpdated, Modifier.fillMaxWidth().padding(10.dp), style = MaterialTheme.typography.labelMedium)
            }
        }
        when {
            settings.connection.address.isBlank() -> EmptyState("请先在设置中配置连接")
            state.loading && state.items.isEmpty() -> LoadingState()
            state.error != null && state.items.isEmpty() -> ErrorState(state.error!!, { viewModel.loadCatalog(reset = true) })
            state.items.isEmpty() -> EmptyState(UiText.EmptyCatalog)
            else -> CatalogList(
                state = listState,
                items = state.items,
                coverPercent = settings.coverWidthPercent,
                imageUrl = viewModel::imageUrl,
                headers = viewModel.imageHeaders(),
                onDirectory = { path -> viewModel.enterDirectory(path, listState.firstVisibleItemIndex) },
                onFile = openDetail,
                loadingMore = state.loadingMore,
            )
        }
    }
    if (showFilters) {
        FiltersDialog(
            initialMin = state.query.ratingMin,
            initialMax = state.query.ratingMax,
            initialSort = state.query.sort,
            initialDirection = state.query.direction,
            initialRecursive = state.query.recursive,
            initialTagIds = state.query.tagIds,
            initialTagMode = state.query.tagMode,
            tags = tags,
            onDismiss = { showFilters = false },
            onApply = { min, max, sort, direction, recursive, tagIds, tagMode ->
                showFilters = false
                viewModel.applyFilters(min, max, sort, direction, recursive, tagIds, tagMode)
            },
        )
    }
}

@Composable
private fun CatalogHeader(
    path: String,
    search: String,
    onSearch: (String) -> Unit,
    onBreadcrumb: (String) -> Unit,
    onFilters: () -> Unit,
    onRefresh: () -> Unit,
) {
    Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
        Text(UiText.Catalog, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { onBreadcrumb("") }) { Text("Content") }
            var accumulated = ""
            path.split('/').filter { it.isNotBlank() }.forEach { part ->
                accumulated = if (accumulated.isEmpty()) part else "$accumulated/$part"
                val target = accumulated
                Text("/", color = MaterialTheme.colorScheme.outline)
                TextButton(onClick = { onBreadcrumb(target) }) { Text(part, maxLines = 1) }
            }
        }
        OutlinedTextField(
            value = search,
            onValueChange = onSearch,
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            label = { Text(UiText.SearchHint) },
        )
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            TextButton(onClick = onRefresh) { Text("刷新") }
            TextButton(onClick = onFilters) { Text(UiText.Filters) }
        }
    }
}

@Composable
private fun CatalogList(
    state: LazyListState,
    items: List<CatalogItemDto>,
    coverPercent: Int,
    imageUrl: (String) -> String?,
    headers: Map<String, String>,
    onDirectory: (String) -> Unit,
    onFile: (String) -> Unit,
    loadingMore: Boolean,
) {
    LazyColumn(state = state, modifier = Modifier.fillMaxSize()) {
        items(items, key = { it.id ?: "directory:${it.relativePath}" }) { item ->
            val width = (80 * coverPercent / 30).dp
            Row(
                Modifier.fillMaxWidth().clickable {
                    if (item.kind == "directory") onDirectory(item.relativePath) else item.id?.let(onFile)
                }.padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (item.kind == "directory") {
                    Surface(Modifier.width(width).aspectRatio(.72f), shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.surfaceVariant) {
                        Box(contentAlignment = Alignment.Center) { Text("目录", style = MaterialTheme.typography.labelMedium) }
                    }
                } else {
                    RemoteImage(
                        url = item.id?.let { imageUrl("api/v1/files/$it/cover") },
                        headers = headers,
                        description = item.name,
                        modifier = Modifier.width(width).aspectRatio(.72f),
                    )
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(item.name, maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
                    val summary = item.tags.filter { it.category in setOf("author", "original", "language") }.joinToString(" · ") { it.value }
                    Text(
                        summary.ifBlank { if (item.kind == "directory") item.relativePath else UiText.Unrecognized },
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        color = MaterialTheme.colorScheme.outline,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                if (item.kind == "file" && item.rating > 0) Text("${item.rating}★", color = MaterialTheme.colorScheme.secondary)
            }
            HorizontalDivider(Modifier.padding(start = 16.dp + width + 14.dp))
        }
        if (loadingMore) item { Box(Modifier.fillMaxWidth().padding(20.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
    }
}

@Composable
private fun FiltersDialog(
    initialMin: Int,
    initialMax: Int,
    initialSort: String,
    initialDirection: String,
    initialRecursive: Boolean,
    initialTagIds: List<Long>,
    initialTagMode: String,
    tags: List<TagCandidateDto>,
    onDismiss: () -> Unit,
    onApply: (Int, Int, String, String, Boolean, List<Long>, String) -> Unit,
) {
    var min by remember { mutableIntStateOf(initialMin) }
    var max by remember { mutableIntStateOf(initialMax) }
    var sort by remember { mutableStateOf(initialSort) }
    var direction by remember { mutableStateOf(initialDirection) }
    var recursive by remember { mutableStateOf(initialRecursive) }
    var selectedTags by remember { mutableStateOf(initialTagIds.toSet()) }
    var tagMode by remember { mutableStateOf(initialTagMode) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(UiText.Filters) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("评分：$min～$max 星")
                Slider(value = min.toFloat(), onValueChange = { min = it.roundToInt().coerceAtMost(max) }, valueRange = 0f..5f, steps = 4)
                Slider(value = max.toFloat(), onValueChange = { max = it.roundToInt().coerceAtLeast(min) }, valueRange = 0f..5f, steps = 4)
                Text("排序")
                Row { listOf("name" to "名称", "modified" to "修改时间", "size" to "大小", "rating" to "评分").forEach { (key, label) -> TextButton(onClick = { sort = key }) { Text(if (sort == key) "• $label" else label) } } }
                Row {
                    TextButton(onClick = { direction = "asc" }) { Text(if (direction == "asc") "• 升序" else "升序") }
                    TextButton(onClick = { direction = "desc" }) { Text(if (direction == "desc") "• 降序" else "降序") }
                    TextButton(onClick = { recursive = !recursive }) { Text(if (recursive) "• 包含子目录" else "当前目录") }
                }
                Text("Tag")
                Row {
                    TextButton(onClick = { tagMode = "all" }) { Text(if (tagMode == "all") "• 同时包含" else "同时包含") }
                    TextButton(onClick = { tagMode = "any" }) { Text(if (tagMode == "any") "• 任一匹配" else "任一匹配") }
                    if (selectedTags.isNotEmpty()) TextButton(onClick = { selectedTags = emptySet() }) { Text("清除") }
                }
                Column(Modifier.height(150.dp).verticalScroll(rememberScrollState())) {
                    tags.forEach { tag ->
                        TextButton(
                            onClick = { selectedTags = if (tag.id in selectedTags) selectedTags - tag.id else selectedTags + tag.id },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(if (tag.id in selectedTags) "✓ ${tag.value} · ${tag.count}" else "${tag.value} · ${tag.count}", Modifier.fillMaxWidth())
                        }
                    }
                }
            }
        },
        confirmButton = { Button(onClick = { onApply(min, max, sort, direction, recursive, selectedTags.toList(), tagMode) }) { Text("应用") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable fun LoadingState() = Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
@Composable fun EmptyState(message: String) = Box(Modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) { Text(message, color = MaterialTheme.colorScheme.outline) }
@Composable fun ErrorState(message: String, retry: () -> Unit) = Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
    Text(message)
    Spacer(Modifier.height(12.dp))
    Button(onClick = retry) { Text(UiText.Retry) }
}
