from __future__ import annotations

import math

from manim import (
    BLUE,
    BLUE_E,
    DOWN,
    FadeIn,
    FadeOut,
    GOLD,
    GREEN,
    GREY_B,
    GREY_D,
    LEFT,
    Line,
    ORANGE,
    Polygon,
    PURPLE,
    RED,
    RIGHT,
    Scene,
    Text,
    UP,
    VGroup,
    WHITE,
    YELLOW,
    Axes,
    Circle,
    DashedLine,
    Dot,
    GrowFromCenter,
    Indicate,
    ReplacementTransform,
    Transform,
    Write,
    Create,
)


POINTS = [
    (0.0, 0.20),
    (0.7, 0.72),
    (1.4, 0.36),
    (2.1, 0.80),
    (2.8, 0.42),
    (3.5, 1.08),
    (4.2, 0.64),
    (4.9, 0.92),
    (5.6, 0.50),
    (6.3, 0.34),
    (7.0, 0.76),
]

PLATEAU_POINTS = [
    (0.0, 0.20),
    (0.7, 0.38),
    (1.4, 0.72),
    (2.1, 0.77),
    (2.8, 0.78),
    (3.5, 0.77),
    (4.2, 0.76),
    (4.9, 0.56),
    (5.6, 0.34),
    (6.3, 0.35),
    (7.0, 0.36),
]

PEAK_POINTS = [
    (0.0, 0.30),
    (0.5, 0.27),
    (1.0, 0.32),
    (1.5, 0.29),
    (2.0, 0.31),
    (2.4, 0.98),
    (2.8, 0.33),
    (3.3, 0.28),
    (3.8, 0.31),
    (4.3, 0.29),
    (4.8, 0.34),
    (5.2, 0.88),
    (5.6, 0.32),
    (6.2, 0.28),
    (7.0, 0.31),
]
def project_point_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[float, float], float]:
    px, py = point
    ax, ay = start
    bx, by = end
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    length_squared = (vx * vx) + (vy * vy)
    if length_squared == 0.0:
        projection = start
    else:
        t = max(0.0, min(1.0, ((wx * vx) + (wy * vy)) / length_squared))
        projection = (ax + (t * vx), ay + (t * vy))
    distance = math.dist(point, projection)
    return projection, distance


def choose_global_farthest(
    selected: list[int],
    points: list[tuple[float, float]] = POINTS,
) -> tuple[int, tuple[float, float], float, tuple[int, int]]:
    best_index = -1
    best_projection = points[0]
    best_distance = -1.0
    best_segment = (selected[0], selected[-1])

    for left, right in zip(selected, selected[1:]):
        for index in range(left + 1, right):
            projection, distance = project_point_to_segment(
                points[index],
                points[left],
                points[right],
            )
            if distance > best_distance:
                best_index = index
                best_projection = projection
                best_distance = distance
                best_segment = (left, right)

    return best_index, best_projection, best_distance, best_segment


def offset_segment(
    start: tuple[float, float],
    end: tuple[float, float],
    distance: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    ax, ay = start
    bx, by = end
    vx = bx - ax
    vy = by - ay
    length = math.hypot(vx, vy)
    nx = -vy / length
    ny = vx / length
    return (ax + (nx * distance), ay + (ny * distance)), (
        bx + (nx * distance),
        by + (ny * distance),
    )


def scaled_points(
    points: list[tuple[float, float]],
    tol_x: float,
    tol_y: float,
) -> list[tuple[float, float]]:
    min_x = min(x for x, _ in points)
    min_y = min(y for _, y in points)
    return [((x - min_x) / tol_x, (y - min_y) / tol_y) for x, y in points]


def project_scene_point_to_segment(point, start, end):
    px, py = point[:2]
    ax, ay = start[:2]
    bx, by = end[:2]
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    length_squared = (vx * vx) + (vy * vy)
    if length_squared == 0.0:
        projection = [ax, ay, 0]
    else:
        t = max(0.0, min(1.0, ((wx * vx) + (wy * vy)) / length_squared))
        projection = [ax + (t * vx), ay + (t * vy), 0]
    distance = math.dist(point[:2], projection[:2])
    return projection, distance

class TsCompressAlgorithm(Scene):
    """Render with: manim -pqh docs/manim/ts_compress_algorithm.py TsCompressAlgorithm."""

    def construct(self) -> None:
        title = Text("ts_compress_to: important points in stretched space", font_size=34)
        title.to_edge(UP)
        self.play(Write(title))

        self.show_selection_sequence(title)
        self.show_stretching_and_tolerance(title)
        self.show_plateau_detection(title)
        self.show_peak_detection(title)
        self.show_feature_engineering(title)
        self.show_large_scale_visualization(title)

    def show_selection_sequence(self, title: Text) -> None:
        axes = Axes(
            x_range=[0, 7, 1],
            y_range=[0, 1.2, 0.2],
            x_length=8.6,
            y_length=4.2,
            axis_config={"color": GREY_B, "include_numbers": False},
            tips=False,
        ).shift(DOWN * 0.25)
        axis_labels = VGroup(
            Text("ORDER BY time", font_size=20).next_to(axes.x_axis, DOWN),
            Text("value", font_size=20).rotate(math.pi / 2).next_to(axes.y_axis, LEFT),
        )
        raw_polyline = self.make_polyline(axes, POINTS, GREY_B, stroke_width=3)
        raw_dots = VGroup(
            *[Dot(axes.c2p(x, y), radius=0.055, color=WHITE) for x, y in POINTS]
        )
        note = Text(
            "Within each partition, endpoints are kept first.",
            font_size=22,
        ).to_edge(DOWN)

        self.play(Create(axes), FadeIn(axis_labels), Create(raw_polyline), FadeIn(raw_dots))
        self.play(FadeIn(note))

        selected = [0, len(POINTS) - 1]
        selected_markers = self.make_selected_dots(axes, POINTS, selected)
        root_segment = Line(
            axes.c2p(*POINTS[selected[0]]),
            axes.c2p(*POINTS[selected[1]]),
            color=YELLOW,
            stroke_width=5,
        )
        compressed_segments = VGroup(root_segment)
        visible_segments = {(selected[0], selected[1]): root_segment}
        selection_artifacts = VGroup(selected_markers, compressed_segments)
        self.play(FadeIn(selected_markers), Create(root_segment))

        for rank in range(1, 4):
            index, projection, distance, segment = choose_global_farthest(selected)
            left, right = segment
            segment_line = Line(
                axes.c2p(*POINTS[left]),
                axes.c2p(*POINTS[right]),
                color=GOLD,
                stroke_width=7,
            )
            point_scene = axes.c2p(*POINTS[index])
            segment_start_scene = axes.c2p(*POINTS[left])
            segment_end_scene = axes.c2p(*POINTS[right])
            projection_scene, _ = project_scene_point_to_segment(
                point_scene,
                segment_start_scene,
                segment_end_scene,
            )
            projection_dot = Dot(projection_scene, radius=0.055, color=RED)
            residual = DashedLine(
                point_scene,
                projection_scene,
                color=RED,
                stroke_width=4,
            )
            right_angle = self.make_right_angle_marker_from_scene_points(
                segment_start_scene,
                segment_end_scene,
                projection_scene,
            )
            vertical_warning = DashedLine(
                point_scene,
                [point_scene[0], projection_scene[1], 0],
                color=GREY_D,
                stroke_width=2,
            )
            vertical_label = Text("not vertical y error", font_size=18, color=GREY_B)
            vertical_label.next_to(vertical_warning, RIGHT, buff=0.15)
            candidate = Dot(axes.c2p(*POINTS[index]), radius=0.095, color=RED)
            label = Text(
                f"Pick #{rank}: distance is perpendicular to the active segment ({distance:.2f}).",
                font_size=21,
            ).to_edge(DOWN)

            self.play(Transform(note, label), Create(segment_line))
            self.play(GrowFromCenter(candidate), Create(residual), FadeIn(projection_dot))
            self.play(Create(right_angle))
            self.play(FadeIn(vertical_warning), FadeIn(vertical_label))
            self.play(FadeOut(vertical_warning), FadeOut(vertical_label), Indicate(residual, color=RED))
            self.wait(0.25)

            parent_segment = visible_segments.pop((left, right))
            left_child = Line(
                axes.c2p(*POINTS[left]),
                axes.c2p(*POINTS[index]),
                color=YELLOW,
                stroke_width=5,
            )
            right_child = Line(
                axes.c2p(*POINTS[index]),
                axes.c2p(*POINTS[right]),
                color=YELLOW,
                stroke_width=5,
            )
            selected.append(index)
            selected.sort()
            visible_segments[(left, index)] = left_child
            visible_segments[(index, right)] = right_child
            compressed_segments.remove(parent_segment)
            compressed_segments.add(left_child, right_child)
            self.play(
                FadeOut(parent_segment),
                Create(left_child),
                Create(right_child),
                FadeOut(segment_line),
                FadeOut(residual),
                FadeOut(projection_dot),
                FadeOut(right_angle),
                Transform(candidate, Dot(axes.c2p(*POINTS[index]), radius=0.085, color=YELLOW)),
            )
            selected_markers.add(candidate)
            selection_artifacts.add(candidate)

        end_note = Text(
            "The selected order becomes compression_importance; the residual becomes compression_distance.",
            font_size=20,
        ).to_edge(DOWN)
        self.play(Transform(note, end_note))
        self.wait(0.8)
        self.play(
            FadeOut(axes),
            FadeOut(axis_labels),
            FadeOut(raw_polyline),
            FadeOut(raw_dots),
            FadeOut(selection_artifacts),
            FadeOut(note),
        )
        self.remove(
            selected_markers,
            compressed_segments,
            selection_artifacts,
            *selected_markers.submobjects,
            *compressed_segments.submobjects,
            *selection_artifacts.submobjects,
        )

    def show_stretching_and_tolerance(self, title: Text) -> None:
        new_title = Text("Stretch first, then measure distance", font_size=34).to_edge(UP)
        self.play(Transform(title, new_title))

        raw_axes = Axes(
            x_range=[0, 7, 1],
            y_range=[0, 1.2, 0.2],
            x_length=4.2,
            y_length=3.0,
            axis_config={"color": GREY_B, "include_numbers": False},
            tips=False,
        ).shift(LEFT * 2.9 + DOWN * 0.35)
        scaled_axes = Axes(
            x_range=[0, 10, 2],
            y_range=[0, 4, 1],
            x_length=4.2,
            y_length=3.0,
            axis_config={"color": GREY_B, "include_numbers": False},
            tips=False,
        ).shift(RIGHT * 2.9 + DOWN * 0.35)
        raw_title = Text("raw units", font_size=22).next_to(raw_axes, UP)
        scaled_title = Text("stretched units", font_size=22).next_to(scaled_axes, UP)
        formula = VGroup(
            Text("x_scaled = (x - x_min) / tol_x", font_size=21),
            Text("y_scaled = (y - y_min) / tol_y", font_size=21),
        ).arrange(DOWN, buff=0.12).to_edge(DOWN)

        tol_x = 0.70
        tol_y = 0.30
        stretched = scaled_points(POINTS, tol_x=tol_x, tol_y=tol_y)
        raw_curve = self.make_polyline(raw_axes, POINTS, GREY_B, stroke_width=3)
        scaled_curve = self.make_polyline(scaled_axes, stretched, BLUE, stroke_width=3)
        raw_dots = VGroup(*[Dot(raw_axes.c2p(*p), radius=0.04, color=WHITE) for p in POINTS])
        scaled_dots = VGroup(*[Dot(scaled_axes.c2p(*p), radius=0.04, color=WHITE) for p in stretched])

        self.play(
            Create(raw_axes),
            Create(scaled_axes),
            FadeIn(raw_title),
            FadeIn(scaled_title),
            Create(raw_curve),
            Create(scaled_curve),
            FadeIn(raw_dots),
            FadeIn(scaled_dots),
            FadeIn(formula),
        )

        x_factor = Text("smaller tol_x => wider x scale", font_size=18, color=BLUE)
        y_factor = Text("smaller tol_y => taller y scale", font_size=18, color=BLUE)
        x_factor.next_to(scaled_axes.x_axis, DOWN)
        y_factor.rotate(math.pi / 2).next_to(scaled_axes.y_axis, LEFT)
        self.play(FadeIn(x_factor), FadeIn(y_factor))

        selected = [0, len(stretched) - 1]
        index, projection, distance, segment = choose_global_farthest(selected, stretched)
        left, right = segment
        active_segment = Line(
            scaled_axes.c2p(*stretched[left]),
            scaled_axes.c2p(*stretched[right]),
            color=GOLD,
            stroke_width=6,
        )
        stretched_point_scene = scaled_axes.c2p(*stretched[index])
        stretched_segment_start = scaled_axes.c2p(*stretched[left])
        stretched_segment_end = scaled_axes.c2p(*stretched[right])
        stretched_projection_scene, _ = project_scene_point_to_segment(
            stretched_point_scene,
            stretched_segment_start,
            stretched_segment_end,
        )
        residual = DashedLine(
            stretched_point_scene,
            stretched_projection_scene,
            color=RED,
            stroke_width=4,
        )
        right_angle = self.make_right_angle_marker_from_scene_points(
            stretched_segment_start,
            stretched_segment_end,
            stretched_projection_scene,
        )
        ball = Circle(radius=0.45, color=GREEN, fill_color=GREEN, fill_opacity=0.12)
        ball.move_to(stretched_projection_scene)
        ball_label = Text("tolerance ball\nradius = distance_max", font_size=18, color=GREEN)
        ball_label.next_to(ball, RIGHT, buff=0.2)
        tolerance_tube = self.make_tolerance_tube(scaled_axes, stretched[left], stretched[right], 0.45)
        note = Text(
            "In stretched space, distance_max is a ball around the segment, not a y-only band.",
            font_size=20,
        ).to_edge(DOWN)

        self.play(Transform(formula, note), Create(active_segment))
        self.play(Create(residual), Create(right_angle), GrowFromCenter(ball), FadeIn(ball_label))
        self.play(Create(tolerance_tube))
        self.wait(1.0)
        self.play(
            FadeOut(raw_axes),
            FadeOut(scaled_axes),
            FadeOut(raw_title),
            FadeOut(scaled_title),
            FadeOut(raw_curve),
            FadeOut(scaled_curve),
            FadeOut(raw_dots),
            FadeOut(scaled_dots),
            FadeOut(x_factor),
            FadeOut(y_factor),
            FadeOut(active_segment),
            FadeOut(residual),
            FadeOut(right_angle),
            FadeOut(ball),
            FadeOut(ball_label),
            FadeOut(tolerance_tube),
            FadeOut(formula),
        )

    def show_plateau_detection(self, title: Text) -> None:
        new_title = Text("Application: plateau detection after compression", font_size=34).to_edge(UP)
        self.play(Transform(title, new_title))

        axes = Axes(
            x_range=[0, 7, 1],
            y_range=[0, 1.0, 0.2],
            x_length=8.6,
            y_length=4.0,
            axis_config={"color": GREY_B, "include_numbers": False},
            tips=False,
        ).shift(DOWN * 0.25)
        raw_curve = self.make_polyline(axes, PLATEAU_POINTS, GREY_B, stroke_width=3)
        raw_dots = VGroup(*[Dot(axes.c2p(*p), radius=0.045, color=WHITE) for p in PLATEAU_POINTS])
        selected = [0, 2, 6, 8, 10]
        compressed = self.make_selected_polyline(axes, PLATEAU_POINTS, selected, YELLOW)
        markers = self.make_selected_dots(axes, PLATEAU_POINTS, selected)
        note = Text(
            "Compress first, then compute slopes between consecutive compressed points.",
            font_size=21,
        ).to_edge(DOWN)
        self.play(Create(axes), Create(raw_curve), FadeIn(raw_dots), FadeIn(note))
        self.play(Create(compressed), FadeIn(markers))

        plateau_segments = VGroup()
        slope_labels = VGroup()
        for left, right in [(2, 6), (8, 10)]:
            segment = Line(
                axes.c2p(*PLATEAU_POINTS[left]),
                axes.c2p(*PLATEAU_POINTS[right]),
                color=GREEN,
                stroke_width=8,
            )
            plateau_segments.add(segment)
            slope = abs(
                (PLATEAU_POINTS[right][1] - PLATEAU_POINTS[left][1])
                / (PLATEAU_POINTS[right][0] - PLATEAU_POINTS[left][0])
            )
            label = Text(f"abs slope = {slope:.2f}", font_size=18, color=GREEN)
            label.next_to(segment, UP, buff=0.15)
            slope_labels.add(label)

        formula = VGroup(
            Text("LEAD(time), LEAD(value)", font_size=19),
            Text("abs_slope <= abs_slope_max", font_size=19, color=GREEN),
            Text("merge adjacent low-slope segments", font_size=19),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.15)
        formula.to_corner(RIGHT + UP).shift(DOWN * 0.7)
        panel = Polygon(
            formula.get_corner(LEFT + DOWN) + LEFT * 0.25 + DOWN * 0.15,
            formula.get_corner(RIGHT + DOWN) + RIGHT * 0.25 + DOWN * 0.15,
            formula.get_corner(RIGHT + UP) + RIGHT * 0.25 + UP * 0.15,
            formula.get_corner(LEFT + UP) + LEFT * 0.25 + UP * 0.15,
            color=GREY_D,
            fill_color=GREY_D,
            fill_opacity=0.7,
            stroke_opacity=0.4,
        )
        next_note = Text(
            "Low-slope compressed segments become plateau ranges for downstream SQL features.",
            font_size=20,
        ).to_edge(DOWN)
        self.play(Transform(note, next_note), FadeIn(panel), FadeIn(formula))
        self.play(Create(plateau_segments), FadeIn(slope_labels))
        for segment in plateau_segments:
            self.play(Indicate(segment, color=GREEN), run_time=0.7)
        self.wait(1.2)
        self.play(
            FadeOut(axes),
            FadeOut(raw_curve),
            FadeOut(raw_dots),
            FadeOut(compressed),
            FadeOut(markers),
            FadeOut(plateau_segments),
            FadeOut(slope_labels),
            FadeOut(panel),
            FadeOut(formula),
            FadeOut(note),
        )

    def show_peak_detection(self, title: Text) -> None:
        new_title = Text("Application: peak detection after compression", font_size=34).to_edge(UP)
        self.play(Transform(title, new_title))

        axes = Axes(
            x_range=[0, 7, 1],
            y_range=[0, 1.15, 0.2],
            x_length=8.6,
            y_length=4.0,
            axis_config={"color": GREY_B, "include_numbers": False},
            tips=False,
        ).shift(DOWN * 0.25)
        raw_curve = self.make_polyline(axes, PEAK_POINTS, GREY_B, stroke_width=3)
        raw_dots = VGroup(*[Dot(axes.c2p(*p), radius=0.045, color=WHITE) for p in PEAK_POINTS])
        selected = [0, 2, 4, 5, 6, 8, 10, 11, 12, 14]
        compressed = self.make_selected_polyline(axes, PEAK_POINTS, selected, YELLOW)
        markers = self.make_selected_dots(axes, PEAK_POINTS, selected)
        note = Text(
            "Compression keeps the two events while smoothing over small baseline noise.",
            font_size=20,
        ).to_edge(DOWN)
        self.play(Create(axes), Create(raw_curve), FadeIn(raw_dots), FadeIn(note))
        self.play(Create(compressed), FadeIn(markers))

        peak_indices = [5, 11]
        peak_markers = VGroup(
            *[
                Circle(radius=0.18, color=ORANGE, stroke_width=5).move_to(axes.c2p(*PEAK_POINTS[i]))
                for i in peak_indices
            ]
        )
        prominence_lines = VGroup()
        peak_labels = VGroup()
        for i in peak_indices:
            floor = min(PEAK_POINTS[i - 1][1], PEAK_POINTS[i + 1][1])
            prominence_lines.add(
                DashedLine(
                    axes.c2p(PEAK_POINTS[i][0], floor),
                    axes.c2p(*PEAK_POINTS[i]),
                    color=ORANGE,
                    stroke_width=3,
                )
            )
            label = Text("peak", font_size=18, color=ORANGE)
            label.next_to(axes.c2p(*PEAK_POINTS[i]), UP, buff=0.12)
            peak_labels.add(label)

        formula = VGroup(
            Text("LAG(value), LEAD(value)", font_size=19),
            Text("value > prev AND value > next", font_size=19, color=ORANGE),
            Text("prominence >= threshold", font_size=19),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.15)
        formula.to_corner(RIGHT + UP).shift(DOWN * 0.7)
        panel = Polygon(
            formula.get_corner(LEFT + DOWN) + LEFT * 0.25 + DOWN * 0.15,
            formula.get_corner(RIGHT + DOWN) + RIGHT * 0.25 + DOWN * 0.15,
            formula.get_corner(RIGHT + UP) + RIGHT * 0.25 + UP * 0.15,
            formula.get_corner(LEFT + UP) + LEFT * 0.25 + UP * 0.15,
            color=GREY_D,
            fill_color=GREY_D,
            fill_opacity=0.7,
            stroke_opacity=0.4,
        )
        next_note = Text(
            "Peak features count events, rank prominences, and measure spacing above the noisy baseline.",
            font_size=20,
        ).to_edge(DOWN)
        self.play(Transform(note, next_note), FadeIn(panel), FadeIn(formula))
        self.play(Create(peak_markers), Create(prominence_lines), FadeIn(peak_labels))
        for marker in peak_markers:
            self.play(Indicate(marker, color=ORANGE), run_time=0.55)
        self.wait(1.2)
        self.play(
            FadeOut(axes),
            FadeOut(raw_curve),
            FadeOut(raw_dots),
            FadeOut(compressed),
            FadeOut(markers),
            FadeOut(peak_markers),
            FadeOut(prominence_lines),
            FadeOut(peak_labels),
            FadeOut(panel),
            FadeOut(formula),
            FadeOut(note),
        )

    def show_feature_engineering(self, title: Text) -> None:
        new_title = Text("Application: feature engineering from the demo", font_size=32).to_edge(UP)
        self.play(Transform(title, new_title))

        families = [
            (
                "trend",
                [(0.0, 0.22), (0.8, 0.31), (1.6, 0.42), (2.4, 0.52), (3.2, 0.63), (4.0, 0.72)],
                GREEN,
                ["reduction_pct  82", "compressed_points  5", "max_distance  0.18"],
                (82, 0.18),
            ),
            (
                "periodic",
                [(0.0, 0.42), (0.6, 0.74), (1.2, 0.40), (1.8, 0.12), (2.4, 0.44), (3.0, 0.76), (3.6, 0.42), (4.2, 0.14)],
                BLUE,
                ["reduction_pct  58", "compressed_points  13", "max_distance  0.54"],
                (58, 0.54),
            ),
            (
                "peaks",
                [(0.0, 0.28), (0.35, 0.30), (0.70, 0.27), (1.05, 0.31), (1.25, 0.95), (1.45, 0.32), (1.85, 0.29), (2.20, 0.31), (2.55, 0.28), (2.95, 0.34), (3.20, 1.00), (3.45, 0.33), (4.20, 0.30)],
                ORANGE,
                ["reduction_pct  46", "compressed_points  18", "max_distance  0.82"],
                (46, 0.82),
            ),
        ]

        note = Text(
            "The demo compresses each series family, then aggregates the selected rows in SQL.",
            font_size=20,
        ).to_edge(DOWN)
        self.play(FadeIn(note))

        strips = VGroup()
        labels = VGroup()
        compressed_lines = VGroup()
        compressed_markers = VGroup()
        raw_lines = VGroup()
        raw_markers = VGroup()
        y_positions = [1.15, -0.05, -1.25]
        for (family, points, color, _, _), y in zip(families, y_positions):
            axes = Axes(
                x_range=[0, 4.2, 1],
                y_range=[0, 1.0, 0.25],
                x_length=3.7,
                y_length=0.85,
                axis_config={"color": GREY_D, "include_numbers": False},
                tips=False,
            ).shift(LEFT * 3.75 + UP * y)
            label = Text(family, font_size=18, color=color).next_to(axes, LEFT, buff=0.25)
            raw = self.make_polyline(axes, points, GREY_B, stroke_width=2.5)
            raw_dots = VGroup(*[Dot(axes.c2p(*p), radius=0.025, color=WHITE) for p in points])
            selected = [0, len(points) // 2, len(points) - 1]
            if family == "periodic":
                selected = [0, 1, 3, 5, 7]
            if family == "peaks":
                selected = [0, 3, 4, 5, 8, 10, 11, 12]
            compressed = self.make_selected_polyline(axes, points, selected, color)
            selected_dots = VGroup(*[Dot(axes.c2p(*points[i]), radius=0.045, color=color) for i in selected])
            strips.add(axes)
            labels.add(label)
            raw_lines.add(raw)
            raw_markers.add(raw_dots)
            compressed_lines.add(compressed)
            compressed_markers.add(selected_dots)

        self.play(FadeIn(labels), Create(strips), Create(raw_lines), FadeIn(raw_markers))
        compress_note = Text(
            "Important points keep the shape; the output table also carries importance and distance.",
            font_size=20,
        ).to_edge(DOWN)
        self.play(Transform(note, compress_note), Create(compressed_lines), FadeIn(compressed_markers))

        table_title = Text("SQL features", font_size=22, color=YELLOW).shift(RIGHT * 2.65 + UP * 1.75)
        table_rows = VGroup()
        for row_index, (family, _, color, metrics, _) in enumerate(families):
            row = VGroup(
                Text(family, font_size=17, color=color),
                *[Text(metric, font_size=16) for metric in metrics],
            ).arrange(RIGHT, buff=0.24)
            row.move_to(RIGHT * 2.75 + UP * (0.95 - row_index * 0.45))
            table_rows.add(row)
        table_panel = Polygon(
            [0.05, -0.72, 0],
            [6.6, -0.72, 0],
            [6.6, 1.55, 0],
            [0.05, 1.55, 0],
            color=GREY_D,
            fill_color=GREY_D,
            fill_opacity=0.55,
            stroke_opacity=0.35,
        )
        feature_note = Text(
            "features_by_mode_sql() computes counts, ratios, reduction_pct, and distance summaries.",
            font_size=19,
        ).to_edge(DOWN)
        self.play(Transform(note, feature_note), FadeIn(table_panel), FadeIn(table_title), FadeIn(table_rows))

        feature_axes = Axes(
            x_range=[35, 90, 15],
            y_range=[0, 1.0, 0.25],
            x_length=4.35,
            y_length=1.75,
            axis_config={"color": GREY_B, "include_numbers": False},
            tips=False,
        ).shift(RIGHT * 2.85 + DOWN * 1.55)
        feature_labels = VGroup(
            Text("reduction_pct", font_size=15).next_to(feature_axes.x_axis, DOWN, buff=0.12),
            Text("max distance", font_size=15).rotate(math.pi / 2).next_to(feature_axes.y_axis, LEFT, buff=0.12),
        )
        feature_points = VGroup()
        feature_names = VGroup()
        for family, _, color, _, coords in families:
            dot = Dot(feature_axes.c2p(*coords), radius=0.065, color=color)
            name = Text(family, font_size=15, color=color).next_to(dot, UP, buff=0.08)
            feature_points.add(dot)
            feature_names.add(name)
        cluster_note = Text(
            "The same demo families separate in feature space: smooth, periodic, and peak-heavy.",
            font_size=19,
        ).to_edge(DOWN)
        self.play(Transform(note, cluster_note), Create(feature_axes), FadeIn(feature_labels), FadeIn(feature_points), FadeIn(feature_names))
        self.wait(1.0)
        self.play(
            FadeOut(strips),
            FadeOut(labels),
            FadeOut(raw_lines),
            FadeOut(raw_markers),
            FadeOut(compressed_lines),
            FadeOut(compressed_markers),
            FadeOut(table_panel),
            FadeOut(table_title),
            FadeOut(table_rows),
            FadeOut(feature_axes),
            FadeOut(feature_labels),
            FadeOut(feature_points),
            FadeOut(feature_names),
            FadeOut(note),
        )
    def show_large_scale_visualization(self, title: Text) -> None:
        new_title = Text("Application: pixel-equivalent visualization", font_size=32).to_edge(UP)
        self.play(Transform(title, new_title))

        left_origin = [-5.55, -1.35, 0]
        right_origin = [0.85, -1.35, 0]
        box_width = 4.75
        box_height = 3.05
        cols = 9
        rows = 6
        cell_w = box_width / cols
        cell_h = box_height / rows

        raw_title = Text("raw table", font_size=22).shift(LEFT * 3.2 + UP * 2.2)
        compressed_title = Text("important points only", font_size=22).shift(RIGHT * 2.9 + UP * 2.2)
        raw_box = Polygon(
            left_origin,
            [left_origin[0] + box_width, left_origin[1], 0],
            [left_origin[0] + box_width, left_origin[1] + box_height, 0],
            [left_origin[0], left_origin[1] + box_height, 0],
            color=GREY_B,
            stroke_width=2,
        )
        compressed_box = Polygon(
            right_origin,
            [right_origin[0] + box_width, right_origin[1], 0],
            [right_origin[0] + box_width, right_origin[1] + box_height, 0],
            [right_origin[0], right_origin[1] + box_height, 0],
            color=GREY_B,
            stroke_width=2,
        )

        raw_cells = [(0, 1), (1, 2), (2, 3), (3, 3), (4, 3), (5, 4), (6, 5), (7, 5), (8, 5)]
        important_cell_indices = [0, 2, 4, 6, 8]
        important_cells = [raw_cells[i] for i in important_cell_indices]

        def cell_center(origin, col, row):
            return [
                origin[0] + (col + 0.5) * cell_w,
                origin[1] + (row + 0.5) * cell_h,
                0,
            ]

        def cell_rect(origin, col, row, color, opacity=0.55):
            x0 = origin[0] + col * cell_w
            y0 = origin[1] + row * cell_h
            inset = 0.025
            return Polygon(
                [x0 + inset, y0 + inset, 0],
                [x0 + cell_w - inset, y0 + inset, 0],
                [x0 + cell_w - inset, y0 + cell_h - inset, 0],
                [x0 + inset, y0 + cell_h - inset, 0],
                color=color,
                fill_color=color,
                fill_opacity=opacity,
                stroke_opacity=0.75,
                stroke_width=1.5,
            )

        def grid(origin):
            lines = VGroup()
            for c in range(1, cols):
                x = origin[0] + c * cell_w
                lines.add(Line([x, origin[1], 0], [x, origin[1] + box_height, 0], color=GREY_D, stroke_width=1))
            for r in range(1, rows):
                y = origin[1] + r * cell_h
                lines.add(Line([origin[0], y, 0], [origin[0] + box_width, y, 0], color=GREY_D, stroke_width=1))
            return lines

        def crossed_cells(cells):
            lit = []
            seen = set()
            for (c0, r0), (c1, r1) in zip(cells, cells[1:]):
                steps = max(abs(c1 - c0), abs(r1 - r0), 1)
                for step in range(steps + 1):
                    t = step / steps
                    col = round(c0 + (c1 - c0) * t)
                    row = round(r0 + (r1 - r0) * t)
                    key = (col, row)
                    if key not in seen:
                        seen.add(key)
                        lit.append(key)
            return lit

        raw_curve_points = [cell_center(left_origin, c, r) for c, r in raw_cells]
        compressed_curve_points = [cell_center(right_origin, c, r) for c, r in important_cells]
        raw_curve = VGroup(
            *[
                Line(a, b, color=WHITE, stroke_width=3)
                for a, b in zip(raw_curve_points, raw_curve_points[1:])
            ]
        )
        raw_dots = VGroup(*[Dot(p, radius=0.035, color=WHITE) for p in raw_curve_points])
        compressed_curve = VGroup(
            *[
                Line(a, b, color=YELLOW, stroke_width=4)
                for a, b in zip(compressed_curve_points, compressed_curve_points[1:])
            ]
        )
        compressed_dots = VGroup(*[Dot(p, radius=0.065, color=YELLOW) for p in compressed_curve_points])
        raw_grid = grid(left_origin)
        compressed_grid = grid(right_origin)
        raw_lit_cells = crossed_cells(raw_cells)
        compressed_lit_cells = crossed_cells(important_cells)
        raw_pixels = VGroup(*[cell_rect(left_origin, c, r, GREEN) for c, r in raw_lit_cells])
        compressed_pixels = VGroup(*[cell_rect(right_origin, c, r, GREEN) for c, r in compressed_lit_cells])

        note = Text("A dense curve may contain many rows per visible pixel.", font_size=21).to_edge(DOWN)
        self.play(FadeIn(raw_title), FadeIn(compressed_title), Create(raw_box), Create(compressed_box), FadeIn(note))
        self.play(Create(raw_curve), FadeIn(raw_dots))

        arrow = Line([-0.55, 0.2, 0], [0.55, 0.2, 0], color=GREEN, stroke_width=5)
        arrow_tip = Polygon([0.55, 0.2, 0], [0.32, 0.34, 0], [0.32, 0.06, 0], color=GREEN, fill_color=GREEN, fill_opacity=1)
        compression_note = Text(
            "Keep only points needed to preserve the pixel footprint.",
            font_size=21,
        ).to_edge(DOWN)
        self.play(Transform(note, compression_note), Create(arrow), FadeIn(arrow_tip), Create(compressed_curve), FadeIn(compressed_dots))

        pixel_note = Text(
            "Overlay the same pixel matrix: every crossed pixel lights up on both sides.",
            font_size=21,
        ).to_edge(DOWN)
        self.play(Transform(note, pixel_note), Create(raw_grid), Create(compressed_grid))
        self.play(FadeIn(raw_pixels), FadeIn(compressed_pixels))

        formula = VGroup(
            Text("effective_width_px = width * plot_x_fraction", font_size=18),
            Text("tol_x = x_range / effective_width_px", font_size=18),
            Text("tol_y = y_range / plot_height_px", font_size=18),
            Text("distance_max = 1 pixel radius", font_size=18, color=GREEN),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12)
        formula.to_edge(DOWN)
        final_note = Text("Same visual result, far fewer rows for TD_PLOT or any plotting layer.", font_size=20).to_edge(DOWN)
        self.play(FadeOut(note), FadeIn(formula))
        self.wait(0.8)
        self.play(Transform(formula, final_note))
        self.wait(1.1)
        self.play(
            FadeOut(raw_title),
            FadeOut(compressed_title),
            FadeOut(raw_box),
            FadeOut(compressed_box),
            FadeOut(raw_curve),
            FadeOut(raw_dots),
            FadeOut(compressed_curve),
            FadeOut(compressed_dots),
            FadeOut(raw_grid),
            FadeOut(compressed_grid),
            FadeOut(raw_pixels),
            FadeOut(compressed_pixels),
            FadeOut(arrow),
            FadeOut(arrow_tip),
            FadeOut(formula),
            FadeOut(title),
        )
    def make_polyline(
        self,
        axes: Axes,
        points: list[tuple[float, float]],
        color,
        stroke_width: float = 4,
    ) -> VGroup:
        return VGroup(
            *[
                Line(
                    axes.c2p(*start),
                    axes.c2p(*end),
                    color=color,
                    stroke_width=stroke_width,
                )
                for start, end in zip(points, points[1:])
            ]
        )

    def make_selected_polyline(
        self,
        axes: Axes,
        points: list[tuple[float, float]],
        selected: list[int],
        color,
    ) -> VGroup:
        return self.make_polyline(
            axes,
            [points[index] for index in selected],
            color,
            stroke_width=5,
        )

    def make_selected_dots(
        self,
        axes: Axes,
        points: list[tuple[float, float]],
        selected: list[int],
    ) -> VGroup:
        return VGroup(
            *[
                Dot(axes.c2p(*points[index]), radius=0.085, color=YELLOW)
                for index in selected
            ]
        )

    def make_right_angle_marker(
        self,
        axes: Axes,
        start: tuple[float, float],
        end: tuple[float, float],
        projection: tuple[float, float],
    ) -> VGroup:
        sx, sy = axes.c2p(*start)[:2]
        ex, ey = axes.c2p(*end)[:2]
        px, py = axes.c2p(*projection)[:2]
        vx = ex - sx
        vy = ey - sy
        length = math.hypot(vx, vy)
        if length == 0.0:
            return VGroup()
        ux = vx / length
        uy = vy / length
        nx = -uy
        ny = ux
        size = 0.16
        corner = [px + (ux * size), py + (uy * size), 0]
        outer = [corner[0] + (nx * size), corner[1] + (ny * size), 0]
        normal = [px + (nx * size), py + (ny * size), 0]
        return VGroup(
            Line(corner, outer, color=RED, stroke_width=3),
            Line(outer, normal, color=RED, stroke_width=3),
        )

    def make_right_angle_marker_from_scene_points(self, start, end, projection) -> VGroup:
        sx, sy = start[:2]
        ex, ey = end[:2]
        px, py = projection[:2]
        vx = ex - sx
        vy = ey - sy
        length = math.hypot(vx, vy)
        if length == 0.0:
            return VGroup()
        ux = vx / length
        uy = vy / length
        nx = -uy
        ny = ux
        size = 0.16
        corner = [px + (ux * size), py + (uy * size), 0]
        outer = [corner[0] + (nx * size), corner[1] + (ny * size), 0]
        normal = [px + (nx * size), py + (ny * size), 0]
        return VGroup(
            Line(corner, outer, color=RED, stroke_width=3),
            Line(outer, normal, color=RED, stroke_width=3),
        )
    def make_tolerance_tube(
        self,
        axes: Axes,
        start: tuple[float, float],
        end: tuple[float, float],
        radius: float,
    ) -> VGroup:
        above = offset_segment(start, end, radius)
        below = offset_segment(start, end, -radius)
        return VGroup(
            DashedLine(axes.c2p(*above[0]), axes.c2p(*above[1]), color=GREEN, stroke_width=2),
            DashedLine(axes.c2p(*below[0]), axes.c2p(*below[1]), color=GREEN, stroke_width=2),
            Circle(radius=0.45, color=GREEN, stroke_opacity=0.55).move_to(axes.c2p(*start)),
            Circle(radius=0.45, color=GREEN, stroke_opacity=0.55).move_to(axes.c2p(*end)),
        )






