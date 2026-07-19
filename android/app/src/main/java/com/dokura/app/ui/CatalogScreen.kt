package com.dokura.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
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
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RangeSlider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.dokura.app.DokuraViewModel
import com.dokura.app.TagOptionsUiState
import com.dokura.app.UiText
import com.dokura.app.data.CatalogItemDto
import com.dokura.app.cache.ImageCache
import com.dokura.app.data.CacheCategory
import com.dokura.app.data.TagCandidateDto
import com.dokura.app.data.TagDto
import kotlin.math.roundToInt
import kotlinx.coroutines.launch

@Composable
fun CatalogScreen(viewModel: DokuraViewModel, openDetail: (String) -> Unit) {
    val state by viewModel.catalog.collectAsState()
    val settings by viewModel.settings.collectAsState()
    val tagOptions by viewModel.tagOptions.collectAsState()
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
                cache = viewModel.imageCache,
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
            tagOptions = tagOptions,
            onReloadTags = { viewModel.loadTags(it) },
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
    var searchVisible by remember { mutableStateOf(search.isNotEmpty()) }
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                UiText.Catalog,
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.SemiBold,
            )
            IconButton(onClick = {
                if (searchVisible) {
                    searchVisible = false
                    onSearch("")
                } else {
                    searchVisible = true
                }
            }) {
                Icon(
                    if (searchVisible) Icons.Default.Close else Icons.Default.Search,
                    contentDescription = if (searchVisible) "关闭搜索" else UiText.SearchHint,
                )
            }
            IconButton(onClick = onRefresh) {
                Icon(Icons.Default.Refresh, contentDescription = "刷新")
            }
            IconButton(onClick = onFilters) {
                Icon(FilterListIcon, contentDescription = UiText.Filters)
            }
        }
        if (searchVisible) {
            OutlinedTextField(
                value = search,
                onValueChange = onSearch,
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                label = { Text(UiText.SearchHint) },
            )
        }
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
    }
}

private val FilterListIcon = ImageVector.Builder(
    name = "FilterList",
    defaultWidth = 24.dp,
    defaultHeight = 24.dp,
    viewportWidth = 24f,
    viewportHeight = 24f,
).apply {
    path(fill = SolidColor(Color.Black)) {
        moveTo(3f, 6f)
        verticalLineTo(8f)
        horizontalLineTo(21f)
        verticalLineTo(6f)
        close()
        moveTo(6f, 11f)
        verticalLineTo(13f)
        horizontalLineTo(18f)
        verticalLineTo(11f)
        close()
        moveTo(10f, 16f)
        verticalLineTo(18f)
        horizontalLineTo(14f)
        verticalLineTo(16f)
        close()
    }
}.build()

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
    cache: ImageCache,
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
                        cache = cache,
                        cacheKey = ImageCache.key(CacheCategory.COVER, requireNotNull(item.id)),
                        category = CacheCategory.COVER,
                        contentVersion = item.contentVersion,
                    )
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        item.name,
                        maxLines = if (item.kind == "directory") 1 else 3,
                        overflow = TextOverflow.Ellipsis,
                        fontWeight = FontWeight.Medium,
                    )
                    if (item.kind == "directory") {
                        CatalogTagLine(item.relativePath)
                    } else {
                        val lines = catalogTagLines(item.tags)
                        if (lines.isEmpty()) CatalogTagLine(UiText.Unrecognized) else lines.forEach { CatalogTagLine(it) }
                    }
                }
                if (item.kind == "file" && item.rating > 0) Text("${item.rating}★", color = MaterialTheme.colorScheme.secondary)
            }
            HorizontalDivider(Modifier.padding(start = 16.dp + width + 14.dp))
        }
        if (loadingMore) item { Box(Modifier.fillMaxWidth().padding(20.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
    }
}

private val CatalogTagCategories = listOf(
    "artist" to "作者",
    "source" to "来源",
    "language" to "语言",
)

internal fun catalogTagLines(tags: List<TagDto>): List<String> = CatalogTagCategories.mapNotNull { (category, label) ->
    tags.filter { it.category == category }.map { it.value }.takeIf { it.isNotEmpty() }
        ?.joinToString("、", prefix = "$label：")
}

@Composable
private fun CatalogTagLine(value: String) {
    Text(
        value,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        color = MaterialTheme.colorScheme.outline,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
internal fun FiltersDialog(
    initialMin: Int,
    initialMax: Int,
    initialSort: String,
    initialDirection: String,
    initialRecursive: Boolean,
    initialTagIds: List<Long>,
    tagOptions: TagOptionsUiState,
    onReloadTags: (Boolean) -> Unit,
    onDismiss: () -> Unit,
    onApply: (Int, Int, String, String, Boolean, List<Long>, String) -> Unit,
) {
    var min by remember { mutableIntStateOf(initialMin) }
    var max by remember { mutableIntStateOf(initialMax) }
    var sort by remember { mutableStateOf(initialSort) }
    var direction by remember { mutableStateOf(initialDirection) }
    var recursive by remember { mutableStateOf(initialRecursive) }
    var selectedTags by remember { mutableStateOf(initialTagIds.toSet()) }
    var activeCategory by remember { mutableStateOf<String?>(null) }
    val categories = listOf("source" to "来源", "artist" to "作者", "language" to "语言")

    if (activeCategory == null) {
        AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text(UiText.Filters) },
            text = {
                Column(
                    Modifier.verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("评分：$min～$max 星")
                    RangeSlider(
                        value = min.toFloat()..max.toFloat(),
                        onValueChange = {
                            min = it.start.roundToInt()
                            max = it.endInclusive.roundToInt()
                        },
                        modifier = Modifier.fillMaxWidth().testTag("ratingRange"),
                        valueRange = 0f..5f,
                        steps = 4,
                    )
                    Text("排序")
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        listOf("name" to "名称", "modified" to "修改时间", "size" to "大小", "rating" to "评分").forEach { (key, label) ->
                            TextButton(onClick = { sort = key }) { Text(if (sort == key) "• $label" else label) }
                        }
                    }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        TextButton(onClick = { direction = "asc" }) { Text(if (direction == "asc") "• 升序" else "升序") }
                        TextButton(onClick = { direction = "desc" }) { Text(if (direction == "desc") "• 降序" else "降序") }
                        TextButton(onClick = {
                            recursive = !recursive
                            onReloadTags(recursive)
                        }) { Text(if (recursive) "• 包含子目录" else "当前目录") }
                    }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("标签", Modifier.weight(1f), fontWeight = FontWeight.Medium)
                        if (selectedTags.isNotEmpty()) TextButton(onClick = { selectedTags = emptySet() }) { Text("清除") }
                    }
                    when {
                        tagOptions.loading -> Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(Modifier.width(24.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("正在加载标签…")
                        }
                        tagOptions.error != null -> Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(tagOptions.error, Modifier.weight(1f), color = MaterialTheme.colorScheme.error)
                            TextButton(onClick = { onReloadTags(recursive) }) { Text("重试") }
                        }
                    }
                    categories.forEach { (category, label) ->
                        TagCategoryField(
                            category = category,
                            label = label,
                            options = tagOptions.items.filter { it.category == category },
                            selectedIds = selectedTags,
                            enabled = !tagOptions.loading && tagOptions.error == null,
                            onClick = { activeCategory = category },
                        )
                    }
                }
            },
            confirmButton = {
                Button(onClick = { onApply(min, max, sort, direction, recursive, selectedTags.toList(), "grouped") }) { Text("应用") }
            },
            dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
        )
    } else {
        val category = requireNotNull(activeCategory)
        val label = requireNotNull(categories.firstOrNull { it.first == category }?.second)
        val options = tagOptions.items.filter { it.category == category }
        val categoryIds = options.mapTo(mutableSetOf()) { it.id }
        TagPickerDialog(
            category = category,
            label = label,
            options = options,
            initialSelected = selectedTags.intersect(categoryIds),
            onDismiss = { activeCategory = null },
            onConfirm = { chosen ->
                selectedTags = (selectedTags - categoryIds) + chosen
                activeCategory = null
            },
        )
    }
}

@Composable
private fun TagCategoryField(
    category: String,
    label: String,
    options: List<TagCandidateDto>,
    selectedIds: Set<Long>,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val selected = options.filter { it.id in selectedIds }
    val summary = when {
        selected.isEmpty() -> "未选择"
        selected.size == 1 -> selected.single().value
        else -> "${selected.first().value} 等 ${selected.size} 项"
    }
    OutlinedButton(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag("tagField:$category"),
        enabled = enabled,
    ) {
        Text(label)
        Spacer(Modifier.weight(1f))
        Text(summary, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun TagPickerDialog(
    category: String,
    label: String,
    options: List<TagCandidateDto>,
    initialSelected: Set<Long>,
    onDismiss: () -> Unit,
    onConfirm: (Set<Long>) -> Unit,
) {
    var search by remember(category) { mutableStateOf("") }
    var selected by remember(category, initialSelected) { mutableStateOf(initialSelected) }
    val filtered = remember(options, search) {
        val keyword = search.trim().lowercase()
        if (keyword.isEmpty()) options else options.filter { it.value.lowercase().contains(keyword) }
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("选择$label（${selected.size}）") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = search,
                    onValueChange = { search = it },
                    modifier = Modifier.fillMaxWidth().testTag("tagSearch:$category"),
                    singleLine = true,
                    label = { Text("搜索$label") },
                )
                if (filtered.isEmpty()) {
                    Box(Modifier.fillMaxWidth().height(96.dp), contentAlignment = Alignment.Center) { Text("没有匹配的标签") }
                } else {
                    LazyColumn(Modifier.fillMaxWidth().heightIn(max = 320.dp)) {
                        items(filtered, key = { it.id }) { tag ->
                            Row(
                                Modifier.fillMaxWidth().heightIn(min = 48.dp)
                                    .clickable { selected = if (tag.id in selected) selected - tag.id else selected + tag.id }
                                    .testTag("tagOption:${tag.id}"),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Checkbox(checked = tag.id in selected, onCheckedChange = null)
                                Spacer(Modifier.width(8.dp))
                                Text("${tag.value}（${tag.count}）", Modifier.weight(1f))
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { Button(onClick = { onConfirm(selected) }) { Text("确定") } },
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
