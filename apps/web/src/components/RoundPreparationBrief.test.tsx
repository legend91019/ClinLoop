import { render, screen } from '@testing-library/react';
import { it, expect } from 'vitest';
import { serve, json } from '../test/server';
import RoundPreparationBrief from './RoundPreparationBrief';
import type { PatientProfile } from '../api/workspaceTypes';

it('shows source facts without needing an actor or model request', async () => {
  const requests = serve((r) =>
    r.url.pathname.endsWith('/round-preparation')
      ? json({
          last_round_at: '2026-11-10T08:00:00Z',
          new_labs: [
            {
              id: 'L1',
              label: 'blood_count_result',
              text: '{"result":"模拟报告已回报"}',
              time: '2026-11-11T08:00:00Z',
            },
          ],
          open_tasks: [],
          last_round: {
            id: 'D1',
            label: '上次查房',
            text: '血培养待回报，过敏史待核实。',
            time: '2026-11-10T08:00:00Z',
          },
          limits: {},
        })
      : undefined,
  );
  render(
    <RoundPreparationBrief
      active
      profile={
        {
          patient_id: 'P1',
          encounter_id: 'E1',
          allergies: '待核实',
          history: '未记录',
        } as PatientProfile
      }
    />,
  );
  expect(await screen.findByText('模拟报告已回报')).toBeInTheDocument();
  expect(screen.getByText('血培养待回报，过敏史待核实。')).toBeInTheDocument();
  expect(requests.every((r) => r.method === 'GET')).toBe(true);
});
