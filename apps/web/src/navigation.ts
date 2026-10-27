export const patientPages = [
  'overview',
  'patients',
  'patient-agent',
  'records',
  'followups',
  'timeline',
  'loops',
  'gaps',
  'trace',
  'handoff',
  'demo',
] as const;
export type PatientPage = (typeof patientPages)[number];

export interface WorkspaceLocation {
  patient: string;
  encounter?: string;
  page: PatientPage;
}

export function readLocation(): WorkspaceLocation {
  const url = new URL(window.location.href);
  const requested = url.searchParams.get('view') || url.hash.slice(1);
  return {
    patient: url.searchParams.get('patient')?.trim() || 'P-1001',
    encounter: url.searchParams.get('encounter')?.trim() || undefined,
    page: patientPages.includes(requested as PatientPage)
      ? (requested as PatientPage)
      : 'overview',
  };
}

export function workspaceUrl(location: WorkspaceLocation): string {
  const url = new URL(window.location.href);
  url.searchParams.set('patient', location.patient);
  url.searchParams.set('view', location.page);
  if (location.encounter) url.searchParams.set('encounter', location.encounter);
  else url.searchParams.delete('encounter');
  url.hash = '';
  return `${url.pathname}${url.search}`;
}
