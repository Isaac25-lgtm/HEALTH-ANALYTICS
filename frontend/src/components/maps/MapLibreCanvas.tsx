"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { dashboardHref, screenForLevel } from "@/lib/scope";
import { formatMeasure, resolveStatus } from "@/lib/status";
import type { MapFeatureCollection } from "@/lib/types";
import "maplibre-gl/dist/maplibre-gl.css";

const FILL: Record<string, string> = {
  green: "#8fd19a",
  yellow: "#f2d16b",
  red: "#ef9a9a",
  blue: "#7eb6e6",
  missing: "#eef3f7",
};

function collectPoints(coordinates: unknown, sink: number[][]) {
  if (!Array.isArray(coordinates) || coordinates.length === 0) {
    return;
  }
  if (typeof coordinates[0] === "number") {
    sink.push(coordinates as number[]);
    return;
  }
  for (const item of coordinates) {
    collectPoints(item, sink);
  }
}

/** Signed area and centroid of one ring (shoelace); screen placement only. */
function ringCentre(ring: number[][]): { area: number; centre: [number, number] } | null {
  if (!Array.isArray(ring) || ring.length < 3) {
    return null;
  }
  let twiceArea = 0;
  let cx = 0;
  let cy = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const [x1, y1] = ring[index];
    const [x2, y2] = ring[(index + 1) % ring.length];
    const cross = x1 * y2 - x2 * y1;
    twiceArea += cross;
    cx += (x1 + x2) * cross;
    cy += (y1 + y2) * cross;
  }
  if (Math.abs(twiceArea) < 1e-12) {
    return null;
  }
  return { area: Math.abs(twiceArea) / 2, centre: [cx / (3 * twiceArea), cy / (3 * twiceArea)] };
}

/** Where a unit's name sits: the centre of its largest polygon, and that polygon's area. */
function labelAnchor(geometry: { type?: string; coordinates?: unknown } | null | undefined) {
  if (!geometry) {
    return null;
  }
  if (geometry.type === "Point") {
    return { area: 0, centre: geometry.coordinates as [number, number] };
  }
  const polygons =
    geometry.type === "Polygon"
      ? [geometry.coordinates as number[][][]]
      : geometry.type === "MultiPolygon"
        ? (geometry.coordinates as number[][][][])
        : [];
  let best: { area: number; centre: [number, number] } | null = null;
  for (const polygon of polygons) {
    const outer = ringCentre(polygon?.[0] ?? []);
    if (outer && (!best || outer.area > best.area)) {
      best = outer;
    }
  }
  return best;
}

/** "Pader District" is labelled "Pader"; a city keeps "City" so it is not mistaken for its district. */
function labelText(name: string): string {
  return name.replace(/\s+District$/i, "");
}

// A map of many units shows only this many names until the viewer zooms in.
const NAMES_ALWAYS_SHOWN = 18;
const ALL_NAMES_UP_TO = 40;

export function MapLibreCanvas({
  features: collectionInput,
  module,
  period,
  comparison,
  selectedCode,
}: {
  features: MapFeatureCollection;
  module: string;
  period: string;
  comparison?: string;
  selectedCode?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const paintSequenceRef = useRef(0);
  const labelsRef = useRef<maplibregl.Marker[]>([]);
  const baseZoomRef = useRef<number | null>(null);
  const navigationRef = useRef({ module, period, comparison, selectedCode });
  navigationRef.current = { module, period, comparison, selectedCode };

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "background", type: "background", paint: { "background-color": "#f5fbff" } }],
      },
      attributionControl: false,
      cooperativeGestures: true,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    // On a crowded map the smaller units are named once the viewer zooms in.
    map.on("zoom", () => {
      const base = baseZoomRef.current;
      if (base != null) {
        containerRef.current?.setAttribute("data-label-detail", map.getZoom() >= base + 0.9 ? "all" : "few");
      }
    });
    mapRef.current = map;
    return () => {
      labelsRef.current.forEach((label) => label.remove());
      labelsRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    const paintSequence = ++paintSequenceRef.current;
    containerRef.current?.setAttribute("data-map-ready", "false");
    let cancelled = false;
    let idleHandler: (() => void) | null = null;
    // Values and statuses are copied from the committed snapshot by the server.
    const features = collectionInput.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        status: resolveStatus(feature.properties),
        label: `${feature.properties.name}: ${formatMeasure(
          feature.properties.raw_value ?? null,
          feature.properties.unit ?? null,
          feature.properties.display_value,
        )}`,
      },
    }));
    const collection = { type: "FeatureCollection" as const, features };
    const apply = () => {
      if (cancelled) {
        return;
      }
      idleHandler = () => {
        if (!cancelled && paintSequenceRef.current === paintSequence) {
          containerRef.current?.setAttribute("data-map-ready", "true");
        }
      };
      // Subscribe before changing the source or camera. A fast paint must not race ahead of the
      // readiness listener used by acceptance screenshots.
      map.once("idle", idleHandler);
      if (map.getSource("units")) {
        (map.getSource("units") as maplibregl.GeoJSONSource).setData(collection as never);
      } else {
        map.addSource("units", { type: "geojson", data: collection as never });
        map.addLayer({
          id: "units-fill",
          type: "fill",
          source: "units",
          filter: ["any", ["==", ["geometry-type"], "Polygon"], ["==", ["geometry-type"], "MultiPolygon"]],
          paint: {
            "fill-color": [
              "match",
              ["get", "status"],
              "green",
              FILL.green,
              "yellow",
              FILL.yellow,
              "red",
              FILL.red,
              "blue",
              FILL.blue,
              FILL.missing,
            ],
            "fill-opacity": 0.85,
            "fill-outline-color": "#06345a",
          },
        });
        map.addLayer({
          id: "units-line",
          type: "line",
          source: "units",
          filter: ["any", ["==", ["geometry-type"], "Polygon"], ["==", ["geometry-type"], "MultiPolygon"]],
          paint: { "line-color": "#06345a", "line-width": 0.8 },
        });
        map.addLayer({
          id: "units-points",
          type: "circle",
          source: "units",
          filter: ["==", ["geometry-type"], "Point"],
          paint: {
            "circle-radius": 5,
            "circle-color": [
              "match",
              ["get", "status"],
              "green",
              FILL.green,
              "yellow",
              FILL.yellow,
              "red",
              FILL.red,
              "blue",
              FILL.blue,
              FILL.missing,
            ],
            "circle-stroke-color": "#06345a",
            "circle-stroke-width": 1,
          },
        });
        const navigateToFeature = (event: maplibregl.MapLayerMouseEvent) => {
          const props = event.features?.[0]?.properties;
          if (!props?.org_unit_id) {
            return;
          }
          const navigation = navigationRef.current;
          window.location.href = dashboardHref({
            screen: screenForLevel(String(props.level_type)),
            orgUnitId: String(props.org_unit_id),
            period: navigation.period,
            comparison: navigation.comparison,
            module: navigation.module,
            indicator: navigation.selectedCode,
          });
        };
        map.on("click", "units-fill", navigateToFeature);
        map.on("click", "units-points", navigateToFeature);
        // Hover shows the unit and its snapshot value; nothing is computed here.
        const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "map-tip" });
        const showTip = (event: maplibregl.MapLayerMouseEvent) => {
          const props = event.features?.[0]?.properties;
          if (!props) {
            return;
          }
          map.getCanvas().style.cursor = "pointer";
          popup.setLngLat(event.lngLat).setText(String(props.label ?? props.name ?? "")).addTo(map);
        };
        const hideTip = () => {
          map.getCanvas().style.cursor = "";
          popup.remove();
        };
        for (const layer of ["units-fill", "units-points"]) {
          map.on("mousemove", layer, showTip);
          map.on("mouseleave", layer, hideTip);
        }
      }
      const points: number[][] = [];
      for (const feature of features) {
        collectPoints(feature.geometry?.coordinates, points);
      }
      if (points.length) {
        const bounds = points.reduce(
          (next, point) => next.extend(point as [number, number]),
          new maplibregl.LngLatBounds(points[0] as [number, number], points[0] as [number, number]),
        );
        // Instant: a data map should present its cohort, not animate a camera into place.
        map.fitBounds(bounds, { padding: 24, duration: 0 });
      }
      // Unit names, drawn as plain HTML over the map (no font files are fetched). They never
      // intercept the pointer, so hover and click still reach the unit beneath.
      labelsRef.current.forEach((label) => label.remove());
      labelsRef.current = [];
      const anchors = features
        .map((feature) => ({ name: String(feature.properties.name ?? ""), anchor: labelAnchor(feature.geometry) }))
        .filter((item) => item.name && item.anchor)
        .sort((a, b) => (b.anchor?.area ?? 0) - (a.anchor?.area ?? 0));
      const crowded = anchors.length > ALL_NAMES_UP_TO;
      anchors.forEach((item, index) => {
        const element = document.createElement("span");
        element.className =
          crowded && index >= NAMES_ALWAYS_SHOWN ? "map-label map-label-minor" : "map-label";
        element.textContent = labelText(item.name);
        labelsRef.current.push(
          new maplibregl.Marker({ element }).setLngLat(item.anchor!.centre as [number, number]).addTo(map),
        );
      });
      baseZoomRef.current = map.getZoom();
      containerRef.current?.setAttribute("data-label-density", crowded ? "crowded" : "open");
      containerRef.current?.setAttribute("data-label-detail", "few");
    };
    if (map.loaded()) {
      apply();
    } else {
      map.once("load", apply);
    }
    return () => {
      cancelled = true;
      map.off("load", apply);
      if (idleHandler) {
        map.off("idle", idleHandler);
      }
    };
  }, [collectionInput, comparison, module, period, selectedCode]);

  return (
    <div
      ref={containerRef}
      className="map-canvas"
      role="application"
      aria-label={`Authorised MapLibre map coloured by ${selectedCode ?? "selected indicator"}`}
    />
  );
}
