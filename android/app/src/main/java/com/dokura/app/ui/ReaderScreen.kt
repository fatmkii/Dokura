package com.dokura.app.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.dokura.app.DokuraViewModel
import com.dokura.app.UiText
import com.dokura.app.reader.ReaderAction
import com.dokura.app.reader.ReaderPolicies
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlin.math.abs

@Composable
fun ReaderScreen(viewModel: DokuraViewModel, onBack: () -> Unit) {
    val state by viewModel.readerState.collectAsState()
    val settings by viewModel.settings.collectAsState()
    val view = LocalView.current
    var zoom by remember { mutableFloatStateOf(1f) }
    var centerX by remember { mutableFloatStateOf(.5f) }
    var centerY by remember { mutableFloatStateOf(.5f) }
    val orientation = LocalConfiguration.current.orientation

    DisposableEffect(settings.keepScreenOn) {
        val previous = view.keepScreenOn
        view.keepScreenOn = settings.keepScreenOn
        onDispose { view.keepScreenOn = previous }
    }
    DisposableEffect(Unit) { onDispose { viewModel.stopReader() } }
    LaunchedEffect(state.page, orientation) { zoom = 1f; centerX = .5f; centerY = .5f }

    fun perform(action: ReaderAction) {
        when (action) {
            ReaderAction.PREVIOUS -> viewModel.reader.goTo(state.page - 1)
            ReaderAction.NEXT -> viewModel.reader.goTo(state.page + 1)
            ReaderAction.TOGGLE_CONTROLS -> viewModel.reader.toggleControls()
            ReaderAction.NONE -> Unit
        }
    }

    val transform = rememberTransformableState { zoomChange, pan, _ ->
        zoom = (zoom * zoomChange).coerceIn(1f, 6f)
        if (zoom > 1.01f) {
            centerX = (centerX - pan.x / (view.width.coerceAtLeast(1) * zoom)).coerceIn(0f, 1f)
            centerY = (centerY - pan.y / (view.height.coerceAtLeast(1) * zoom)).coerceIn(0f, 1f)
        } else {
            centerX = .5f
            centerY = .5f
        }
    }

    BoxWithConstraints(
        Modifier.fillMaxSize().background(Color.Black)
            .readerPageGestures(state.page, settings.readingDirection, zoom, ::perform) {
                zoom = if (zoom > 1.01f) 1f else 2f
                if (zoom == 1f) { centerX = .5f; centerY = .5f }
            },
        contentAlignment = Alignment.Center,
    ) {
        val density = LocalDensity.current
        val widthPx = with(density) { maxWidth.roundToPx() }
        val heightPx = with(density) { maxHeight.roundToPx() }
        LaunchedEffect(state.page, zoom, centerX, centerY, widthPx, heightPx) {
            delay(80)
            viewModel.reader.showViewport(zoom, centerX, centerY, widthPx, heightPx)
        }
        when {
            state.bitmap != null -> Image(
                bitmap = (state.regionBitmap ?: state.bitmap!!).asImageBitmap(),
                contentDescription = "第 ${state.page} 页",
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize().graphicsLayer(
                    scaleX = if (state.regionBitmap == null) zoom else 1f,
                    scaleY = if (state.regionBitmap == null) zoom else 1f,
                ).transformable(transform).testTag("readerImage"),
            )
            state.unavailable -> Text(UiText.PageUnavailable, color = Color.White)
            state.loading -> CircularProgressIndicator(color = Color.White)
            state.error != null -> Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(UiText.ImageReadFailed, color = Color.White)
                Text(state.error!!, color = Color.LightGray, style = MaterialTheme.typography.bodySmall)
                Row {
                    Button(onClick = viewModel.reader::retry) { Text(UiText.Retry) }
                    TextButton(onClick = onBack) { Text(UiText.BackToDetail, color = Color.White) }
                }
            }
        }

        if (state.error != null && (state.bitmap != null || state.unavailable)) {
            Row(
                Modifier.align(Alignment.Center).background(Color(0xCC202020)).padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(UiText.ImageReadFailed, color = Color.White)
                TextButton(onClick = viewModel.reader::retry) { Text(UiText.Retry) }
            }
        }

        if (state.controlsVisible && state.item != null) {
            Row(
                Modifier.align(Alignment.TopCenter).fillMaxWidth().background(Color(0xB0000000)).padding(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onBack) { Text("返回", color = Color.White) }
                Text(state.item!!.name, Modifier.weight(1f), color = Color.White, maxLines = 1)
            }
            Column(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Color(0xB0000000)).padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("${state.page} / ${state.item!!.pageCount}", color = Color.White)
                Slider(
                    value = state.page.toFloat(),
                    onValueChange = { viewModel.reader.goTo(it.toInt()) },
                    valueRange = 1f..state.item!!.pageCount.coerceAtLeast(1).toFloat(),
                    steps = (state.item!!.pageCount - 2).coerceAtLeast(0),
                    modifier = Modifier.testTag("pageSlider"),
                )
            }
        }
    }
}

internal fun Modifier.readerPageGestures(
    page: Int,
    direction: com.dokura.app.data.ReadingDirection,
    zoom: Float,
    onAction: (ReaderAction) -> Unit,
    onDoubleTap: () -> Unit = {},
): Modifier = pointerInput(page, direction, zoom) {
    coroutineScope {
        var pendingTap: Job? = null
        var previousTapAt = 0L
        var previousTapX = 0f
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false)
            var totalX = 0f
            var totalY = 0f
            var multiTouch = false
            var pressed = true
            while (pressed) {
                val event = awaitPointerEvent()
                if (event.changes.size > 1) multiTouch = true
                val change = event.changes.firstOrNull { it.id == down.id } ?: break
                totalX += change.position.x - change.previousPosition.x
                totalY += change.position.y - change.previousPosition.y
                pressed = change.pressed
                if (!multiTouch && abs(totalX) > viewConfiguration.touchSlop && abs(totalX) > abs(totalY)) change.consume()
            }
            if (multiTouch) return@awaitEachGesture
            if (abs(totalX) > viewConfiguration.touchSlop && abs(totalX) > abs(totalY)) {
                pendingTap?.cancel()
                onAction(ReaderPolicies.swipe(totalX, direction, zoom))
            } else {
                val now = down.uptimeMillis
                val doubleTap = previousTapAt != 0L && now - previousTapAt <= viewConfiguration.doubleTapTimeoutMillis &&
                    abs(down.position.x - previousTapX) <= viewConfiguration.touchSlop * 4
                if (doubleTap) {
                    pendingTap?.cancel()
                    previousTapAt = 0
                    onDoubleTap()
                } else {
                    previousTapAt = now
                    previousTapX = down.position.x
                    pendingTap = launch {
                        delay(viewConfiguration.doubleTapTimeoutMillis)
                        onAction(ReaderPolicies.edgeTap(down.position.x / size.width, direction))
                    }
                }
            }
        }
    }
}
