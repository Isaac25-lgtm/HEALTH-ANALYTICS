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
    mapRef.current = map;
    return () => {
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
