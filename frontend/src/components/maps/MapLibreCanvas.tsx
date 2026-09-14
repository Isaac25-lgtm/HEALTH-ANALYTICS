"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { dashboardHref, screenForLevel } from "@/lib/scope";
import { resolveStatus } from "@/lib/status";
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
    // Values and statuses are copied from the committed snapshot by the server.
    const features = collectionInput.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        status: resolveStatus(feature.properties),
        label: `${feature.properties.name}: ${feature.properties.display_value ?? "No data"}`,
      },
    }));
    const collection = { type: "FeatureCollection" as const, features };
    const apply = () => {
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
        map.on("click", "units-fill", (event) => {
          const props = event.features?.[0]?.properties;
          if (!props?.org_unit_id) {
            return;
          }
          window.location.href = dashboardHref({
            screen: screenForLevel(String(props.level_type)),
            orgUnitId: String(props.org_unit_id),
            period,
            comparison,
            module,
            indicator: selectedCode,
          });
        });
        map.on("click", "units-points", (event) => {
          const props = event.features?.[0]?.properties;
          if (!props?.org_unit_id) {
            return;
          }
          window.location.href = dashboardHref({
            screen: screenForLevel(String(props.level_type)),
            orgUnitId: String(props.org_unit_id),
            period,
            comparison,
            module,
            indicator: selectedCode,
          });
        });
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
        map.fitBounds(bounds, { padding: 24, duration: 400 });
      }
    };
    if (map.loaded()) {
      apply();
    } else {
      map.once("load", apply);
    }
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
