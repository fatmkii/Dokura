package com.dokura.app

import android.content.pm.ActivityInfo
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.os.ParcelFileDescriptor
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeLeft
import androidx.compose.ui.test.click
import com.dokura.app.data.ReadingDirection
import com.dokura.app.data.TagCandidateDto
import com.dokura.app.reader.ReaderAction
import com.dokura.app.ui.FiltersDialog
import com.dokura.app.ui.RatingSelector
import com.dokura.app.ui.readerPageGestures
import org.junit.Rule
import org.junit.Before
import org.junit.Test
import org.junit.Assert.assertEquals
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainActivityTest {
    @get:Rule val composeRule = createAndroidComposeRule<MainActivity>()

    @Before fun portrait() {
        composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        composeRule.waitForIdle()
    }

    @Test fun catalogRecentAndSettingsNavigationIsAvailable() {
        composeRule.onNodeWithContentDescription(UiText.SearchHint).assertIsDisplayed()
        composeRule.onNodeWithText(UiText.RecentNav).performClick()
        composeRule.onNodeWithText(UiText.Recent).assertIsDisplayed()
        composeRule.onNodeWithText(UiText.Settings).performClick()
        composeRule.onNodeWithTag("serverAddress").assertIsDisplayed()
    }

    @Test fun apiKeyIsMaskedAndThemeChangePreservesFormState() {
        composeRule.onNodeWithText(UiText.Settings).performClick()
        composeRule.onNodeWithTag("serverAddress").performTextClearance()
        composeRule.onNodeWithTag("serverAddress").performTextInput("192.168.1.8")
        composeRule.onNodeWithTag("apiKey").performTextInput("never-show-this-key")
        composeRule.onNodeWithTag("choice:暗色").performScrollTo().performClick()
        composeRule.onNodeWithTag("serverAddress").assertTextContains("192.168.1.8")
        composeRule.onNodeWithTag("apiKey").assert(SemanticsMatcher.keyIsDefined(SemanticsProperties.Password))
    }

    @Test fun gridChoicesRemainAvailableAfterRotation() {
        composeRule.onNodeWithText(UiText.Settings).performClick()
        composeRule.onNodeWithTag("choice:5 列").performScrollTo().performClick()
        composeRule.onNodeWithTag("choice:5 列").assertIsSelected()
        composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        composeRule.waitUntil(5_000) {
            composeRule.onAllNodesWithTag("choice:5 列").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("choice:5 列").assertIsSelected()
        composeRule.onNodeWithText("4 列").assertExists()
        composeRule.onNodeWithText("6 列").assertExists()
    }

    @Test fun settingsRemainUsableAtTwoHundredPercentFontScale() {
        val original = composeRule.activity.resources.configuration.fontScale
        try {
            shell("settings put system font_scale 2.0")
            composeRule.activityRule.scenario.recreate()
            composeRule.waitUntil(5_000) { composeRule.activity.resources.configuration.fontScale >= 1.9f }
            composeRule.onNodeWithText(UiText.Settings).performClick()
            composeRule.onNodeWithTag("serverAddress").assertIsDisplayed()
            composeRule.onNodeWithTag("choice:6 列").performScrollTo().assertIsDisplayed()
        } finally {
            shell("settings put system font_scale $original")
            composeRule.activityRule.scenario.recreate()
        }
    }

    @Test fun stageSevenReadingAndCacheSettingsPersistAcrossRotation() {
        composeRule.onNodeWithText(UiText.Settings).performClick()
        composeRule.onNodeWithTag("choice:${UiText.RightToLeft}").performScrollTo().performClick()
        composeRule.onNodeWithTag("keepScreenOn").performScrollTo().performClick()
        composeRule.onNodeWithTag("choice:10 GB").performScrollTo().performClick()
        composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        composeRule.waitUntil(5_000) {
            composeRule.onAllNodesWithTag("choice:${UiText.RightToLeft}").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("choice:${UiText.RightToLeft}").assertIsSelected()
        composeRule.onNodeWithTag("choice:10 GB").assertIsSelected()
    }

    @Test fun readerGestureLayerUsesDirectionAndBlocksZoomedDragButKeepsEdgeTap() {
        var action by mutableStateOf(ReaderAction.NONE)
        var direction by mutableStateOf(ReadingDirection.LEFT_TO_RIGHT)
        var zoom by mutableStateOf(1f)
        composeRule.activity.setContent {
            Box(
                Modifier.fillMaxSize().testTag("gestureLayer")
                    .readerPageGestures(1, direction, zoom, { action = it }),
            ) { Text(action.name) }
        }
        composeRule.onNodeWithTag("gestureLayer").performTouchInput { swipeLeft() }
        composeRule.runOnIdle { assertEquals(ReaderAction.NEXT, action) }

        composeRule.runOnIdle { action = ReaderAction.NONE; zoom = 2f }
        composeRule.onNodeWithTag("gestureLayer").performTouchInput { swipeLeft() }
        composeRule.runOnIdle { assertEquals(ReaderAction.NONE, action) }

        composeRule.onNodeWithTag("gestureLayer").performTouchInput { click(centerRight) }
        composeRule.waitUntil(1_000) { action == ReaderAction.NEXT }
        composeRule.runOnIdle { assertEquals(ReaderAction.NEXT, action) }

        composeRule.runOnIdle { action = ReaderAction.NONE; direction = ReadingDirection.RIGHT_TO_LEFT }
        composeRule.onNodeWithTag("gestureLayer").performTouchInput { click(centerLeft) }
        composeRule.waitUntil(1_000) { action == ReaderAction.NEXT }
        composeRule.runOnIdle { assertEquals(ReaderAction.NEXT, action) }
    }

    @Test fun detailRatingShowsFiveTouchableStars() {
        var rating by mutableStateOf(3)
        composeRule.activity.setContent {
            MaterialTheme { RatingSelector(rating, saving = false) { rating = it } }
        }

        (1..5).forEach { composeRule.onNodeWithTag("rating:$it").assertIsDisplayed() }
        composeRule.onNodeWithTag("rating:5").performClick()
        composeRule.runOnIdle { assertEquals(5, rating) }
    }

    @Test fun filtersUseRangeAndSearchableGroupedTagSelectors() {
        var appliedIds = emptyList<Long>()
        var appliedMode = ""
        composeRule.activity.setContent {
            MaterialTheme {
                FiltersDialog(
                    initialMin = 0,
                    initialMax = 5,
                    initialSort = "name",
                    initialDirection = "asc",
                    initialRecursive = false,
                    initialTagIds = emptyList(),
                    tagOptions = TagOptionsUiState(
                        items = listOf(
                            TagCandidateDto(1, "artist", "作者甲", 12),
                            TagCandidateDto(2, "artist", "作者乙", 7),
                            TagCandidateDto(3, "source", "原作甲", 5),
                            TagCandidateDto(4, "language", "zh", 20),
                        ),
                    ),
                    onReloadTags = { _ -> },
                    onDismiss = {},
                    onApply = { _, _, _, _, _, ids, mode -> appliedIds = ids; appliedMode = mode },
                )
            }
        }

        composeRule.onNodeWithTag("ratingRange").assertExists()
        composeRule.onNodeWithTag("tagField:source").assertExists()
        composeRule.onNodeWithTag("tagField:artist").performClick()
        composeRule.waitUntil(5_000) {
            composeRule.onAllNodesWithTag("tagSearch:artist").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithTag("tagSearch:artist").performTextInput("甲")
        composeRule.onNodeWithTag("tagOption:1").performClick()
        composeRule.onNodeWithText("确定").performClick()
        composeRule.onNodeWithText("应用").performClick()
        composeRule.runOnIdle {
            assertEquals(listOf(1L), appliedIds)
            assertEquals("grouped", appliedMode)
        }
    }

    private fun shell(command: String) {
        val descriptor = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(command)
        ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { it.readBytes() }
    }
}
