import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MapFeatureCollection } from "@/lib/types";

type LayerClick = (event: {
  features?: Array<{ properties?: Record<string, unknown> }>;
}) => void;

type FakeSource = { setData: ReturnType<typeof vi.fn> };

type FakeMapInstance = {
  handlers: Map<string, LayerClick>;
  idleHandlers: Set<() => void>;
  sources: Map<string, FakeSource>;
  emitIdle: () => void;
  click: (layer: string, properties: Record<string, unknown>) => void;
};

const harness = vi.hoisted(() => ({
  instances: [] as FakeMapInstance[],
  dashboardHref: vi.fn(() => "#mapped-unit"),
}));

vi.mock("@/lib/scope", async () => {
  const actual = await vi.importActual<typeof import("@/lib/scope")>("@/lib/scope");
  return { ...actual, dashboardHref: harness.dashboardHref };
});

vi.mock("maplibre-gl", () => {
  class FakeMap {
    handlers = new globalThis.Map<string, LayerClick>();
    idleHandlers = new Set<() => void>();
    sources = new globalThis.Map<string, FakeSource>();

    constructor() {
      harness.instances.push(this);
    }

    addControl() {}

    remove() {}

    loaded() {
      return true;
    }

    getSource(id: string) {
      return this.sources.get(id);
    }

    addSource(id: string) {
      this.sources.set(id, { setData: vi.fn() });
    }

    addLayer() {}

    fitBounds() {}

    on(event: string, layer: string, handler: LayerClick) {
      this.handlers.set(`${event}:${layer}`, handler);
    }

    once(event: string, handler: () => void) {
      if (event === "idle") {
        this.idleHandlers.add(handler);
      } else {
        handler();
      }
    }

    off(event: string, layerOrHandler: string | (() => void), possibleHandler?: LayerClick) {
      if (event === "idle" && typeof layerOrHandler === "function") {
        this.idleHandlers.delete(layerOrHandler);
      }
      if (typeof layerOrHandler === "string" && possibleHandler) {
        this.handlers.delete(`${event}:${layerOrHandler}`);
      }
    }

    getCanvas() {
      return { style: {} as Record<string, string> };
    }

    emitIdle() {
      const queued = [...this.idleHandlers];
      this.idleHandlers.clear();
      queued.forEach((handler) => handler());
    }

    click(layer: string, properties: Record<string, unknown>) {
      this.handlers.get(`click:${layer}`)?.({ features: [{ properties }] });
    }
  }

  class FakeBounds {
    extend() {
      return this;
    }
  }

  return {
    default: {
      Map: FakeMap,
      NavigationControl: class {},
      Popup: class {
        setLngLat() {
          return this;
        }
        setText() {
          return this;
        }
        addTo() {
          return this;
        }
        remove() {}
      },
      LngLatBounds: FakeBounds,
    },
  };
});

import { MapLibreCanvas } from "@/components/maps/MapLibreCanvas";

function features(code: string): MapFeatureCollection {
  return {
    type: "FeatureCollection",
    map_state: "mapped",
    mapping_note: null,
    map_level: "district",
    selected_indicator: "ANC1_COVERAGE",
    geometry_effective_date: "2024-07-01",
    feature_count: 1,
    missing_geometry_ids: [],
    missing_value_ids: [],
    features: [
      {
        type: "Feature",
        id: `feature-${code}`,
        properties: {
          org_unit_id: `org-${code}`,
          code,
          name: code,
          level_type: "district",
          parent_id: "country-1",
          indicator_code: "ANC1_COVERAGE",
          raw_value: 75,
          display_value: "75.0%",
          unit: "%",
          status: "yellow",
          quality_status: null,
          calculation_run_id: "run-1",
        },
        geometry: {
          type: "Polygon",
          coordinates: [[[32, 2], [33, 2], [33, 3], [32, 2]]],
        },
      },
    ],
  };
}

describe("MapLibreCanvas", () => {
  beforeEach(() => {
    harness.instances.length = 0;
    harness.dashboardHref.mockClear();
    window.location.hash = "";
  });

  it("uses current filters for drill-down and resets readiness for every paint", async () => {
    const { container, rerender } = render(
      <MapLibreCanvas
        features={features("PADER")}
        module="anc"
        period="FY2024/25"
        comparison="FY2023/24"
        selectedCode="ANC1_COVERAGE"
      />,
    );

    await waitFor(() => expect(harness.instances).toHaveLength(1));
    const map = harness.instances[0];
    const canvas = container.querySelector(".map-canvas");
    expect(canvas).toHaveAttribute("data-map-ready", "false");

    act(() => map.emitIdle());
    expect(canvas).toHaveAttribute("data-map-ready", "true");

    rerender(
      <MapLibreCanvas
        features={features("KITGUM")}
        module="immunization"
        period="FY2026/27"
        comparison="FY2025/26"
        selectedCode="MR_COVERAGE"
      />,
    );
    await waitFor(() => expect(canvas).toHaveAttribute("data-map-ready", "false"));

    act(() =>
      map.click("units-fill", {
        org_unit_id: "org-KITGUM",
        level_type: "district",
      }),
    );
    expect(harness.dashboardHref).toHaveBeenLastCalledWith({
      screen: "district",
      orgUnitId: "org-KITGUM",
      period: "FY2026/27",
      comparison: "FY2025/26",
      module: "immunization",
      indicator: "MR_COVERAGE",
    });

    act(() => map.emitIdle());
    expect(canvas).toHaveAttribute("data-map-ready", "true");
  });
});
