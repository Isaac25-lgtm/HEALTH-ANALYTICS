from datetime import date

from app.services.geometry import intervals_overlap, simplify_geojson, simplify_ring


def test_closed_ring_remains_valid_after_simplification():
    ring = [
        [0.0, 0.0],
        [0.001, 0.0],
        [1.0, 0.0],
        [1.0, 1.0],
        [0.0, 1.0],
        [0.0, 0.0],
    ]
    simplified = simplify_ring(ring, epsilon=0.01)
    assert simplified[0] == simplified[-1]
    assert len(simplified) >= 4
    assert len(simplified) < len(ring)


def test_simplify_does_not_overwrite_source_polygon_identity():
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [32.0, 1.0],
                [32.01, 1.0],
                [33.0, 1.0],
                [33.0, 2.0],
                [32.0, 2.0],
                [32.0, 1.0],
            ]
        ],
    }
    original = [list(point) for point in geometry["coordinates"][0]]
    simplified = simplify_geojson(geometry, epsilon=0.05)
    assert geometry["coordinates"][0] == original
    assert simplified["type"] == "Polygon"
    assert simplified["coordinates"][0][0] == simplified["coordinates"][0][-1]


def test_geometry_validity_intervals_overlap_is_detected():
    assert intervals_overlap(date(2024, 1, 1), date(2024, 12, 31), date(2024, 6, 1), None)
    assert not intervals_overlap(date(2020, 1, 1), date(2023, 12, 31), date(2024, 1, 1), None)
