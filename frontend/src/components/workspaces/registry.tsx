import type { ComponentType } from "react";
import type { CompositionKey } from "@/lib/workspaces";
import {
  AdminWorkspace,
  AiWorkspace,
  MapsWorkspace,
  QualityWorkspace,
  ReportsWorkspace,
  TrendsWorkspace,
} from "./AnalyticalCompositions";
import { FacilityProfile, GeographyOverview } from "./GeographyCompositions";
import { AncWorkspace, ImmunizationWorkspace, IntrapartumWorkspace, MpdsrWorkspace } from "./ProgrammeCompositions";
import type { CompositionProps } from "./types";

/** One composition component per screen family and workspace, all built from shared panels. */
export const COMPOSITIONS: Record<CompositionKey, ComponentType<CompositionProps>> = {
  geography: GeographyOverview,
  facility: FacilityProfile,
  anc: AncWorkspace,
  intrapartum: IntrapartumWorkspace,
  immunization: ImmunizationWorkspace,
  mpdsr: MpdsrWorkspace,
  maps: MapsWorkspace,
  trends: TrendsWorkspace,
  quality: QualityWorkspace,
  reports: ReportsWorkspace,
  ai: AiWorkspace,
  admin: AdminWorkspace,
};
