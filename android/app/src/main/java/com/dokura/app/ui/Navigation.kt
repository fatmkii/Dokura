package com.dokura.app.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.dokura.app.DokuraViewModel
import com.dokura.app.UiText

private data class Destination(val route: String, val label: String, val mark: String)
private val destinations = listOf(
    Destination("catalog", UiText.Catalog, "库"),
    Destination("recent", UiText.Recent, "近"),
    Destination("settings", UiText.Settings, "设"),
)

@Composable
fun DokuraNavigation(viewModel: DokuraViewModel) {
    val controller = rememberNavController()
    val route = controller.currentBackStackEntryAsState().value?.destination?.route
    val showBottom = route != "detail/{id}" && route != "reader/{id}/{page}"
    Scaffold(
        bottomBar = {
            if (showBottom) NavigationBar {
                destinations.forEach { destination ->
                    NavigationBarItem(
                        selected = route == destination.route,
                        onClick = {
                            controller.navigate(destination.route) {
                                popUpTo("catalog") { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = { Text(destination.mark) },
                        label = { Text(destination.label) },
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(if (showBottom) padding else androidx.compose.foundation.layout.PaddingValues())) {
            NavHost(controller, startDestination = "catalog") {
                composable("catalog") {
                    CatalogScreen(viewModel) { id -> controller.navigate("detail/$id") }
                }
                composable("recent") {
                    RecentScreen(viewModel) { id -> controller.navigate("detail/$id") }
                }
                composable("settings") { SettingsScreen(viewModel) }
                composable(
                    "detail/{id}",
                    arguments = listOf(navArgument("id") { type = NavType.StringType }),
                ) { entry ->
                    DetailScreen(
                        viewModel = viewModel,
                        id = requireNotNull(entry.arguments?.getString("id")),
                        onBack = { controller.popBackStack() },
                        onRead = { page ->
                            viewModel.startReader(page)
                            controller.navigate("reader/${requireNotNull(entry.arguments?.getString("id"))}/$page")
                        },
                    )
                }
                composable(
                    "reader/{id}/{page}",
                    arguments = listOf(
                        navArgument("id") { type = NavType.StringType },
                        navArgument("page") { type = NavType.IntType },
                    ),
                ) {
                    ReaderScreen(viewModel) { controller.popBackStack() }
                }
            }
        }
    }
}
