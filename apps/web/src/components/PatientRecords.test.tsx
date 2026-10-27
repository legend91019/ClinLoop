import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { json, serve } from '../test/server';
import type { ClinicalDocument, PatientProfile } from '../api/workspaceTypes';
import PatientRecords from './PatientRecords';

const profile: PatientProfile = {
  patient_id: 'P-2001',
  encounter_id: 'ENC-3001',
  display_name: '林晓禾（模拟）',
  sex: '女',
  age: 34,
  ward: '模拟病区',
  bed: '01',
  chief_complaint: '资料随访',
  history: '待补录',
  allergies: '待核对',
  admitted_at: null,
  synthetic: true,
  open_tasks: 0,
};
const actor = { actor_id: 'DR-TEST', role: 'PHYSICIAN' as const };

describe('patient records workspace', () => {
  it('saves an edited round note for this encounter, submits it and locks the text', async () => {
    let document: ClinicalDocument | undefined;
    const requests = serve((r) => {
      if (r.url.pathname.endsWith('/documents') && r.method === 'GET')
        return json(document ? [document] : []);
      if (r.url.pathname.endsWith('/tasks')) return json([]);
      if (r.url.pathname.endsWith('/documents') && r.method === 'POST') {
        document = {
          ...r.body,
          document_id: 'DOC-TEST',
          patient_id: profile.patient_id,
          status: 'DRAFT',
          revision: 1,
          author_id: actor.actor_id,
          created_at: '2026-10-26T08:00:00Z',
          updated_at: '2026-10-26T08:00:00Z',
          submitted_at: null,
          event_id: null,
        } as ClinicalDocument;
        return json(document, 201);
      }
      if (r.url.pathname.endsWith('/DOC-TEST') && r.method === 'PATCH') {
        document = { ...document!, ...r.body, revision: 2 } as ClinicalDocument;
        return json(document);
      }
      if (r.url.pathname.endsWith('/submit')) {
        document = {
          ...document!,
          status: 'SUBMITTED',
          revision: 3,
          event_id: 'EVT-TEST',
        };
        return json(document);
      }
      return undefined;
    });
    const onChanged = vi.fn();
    render(
      <PatientRecords
        profile={profile}
        actor={actor}
        onChanged={onChanged}
        onDirtyChange={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '查房记录' }));
    fireEvent.change(screen.getByLabelText('记录正文'), {
      target: { value: '本次查房：核对检查报告，继续跟进。' },
    });
    await userEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    await screen.findByText('草稿已保存，可以稍后继续编辑。');
    const saved = requests.find(
      (r) => r.method === 'POST' && r.url.pathname.endsWith('/documents'),
    );
    expect(saved?.body).toMatchObject({
      encounter_id: 'ENC-3001',
      kind: 'ROUND',
      content: '本次查房：核对检查报告，继续跟进。',
    });
    expect(saved?.url.pathname).toContain('/P-2001/');
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await userEvent.click(screen.getByRole('button', { name: '提交记录' }));
    await screen.findByText('已提交记录 · 只读');
    expect(screen.getByLabelText('记录正文')).toHaveAttribute('readonly');
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it('creates a task with the selected patient and requires a written completion note', async () => {
    let tasks: unknown[] = [];
    const task = {
      loop_id: 'LOOP-TEST',
      patient_id: 'P-2001',
      encounter_id: 'ENC-3001',
      goal: '核对报告',
      state: 'PLANNED',
      priority: 'HIGH',
      owner: 'DR-TEST',
      due_at: null,
      source_document_id: null,
      history: [],
    };
    const requests = serve((r) => {
      if (r.url.pathname.endsWith('/documents')) return json([]);
      if (r.url.pathname.endsWith('/tasks') && r.method === 'GET')
        return json(tasks);
      if (r.url.pathname.endsWith('/tasks') && r.method === 'POST') {
        tasks = [task];
        return json(task, 201);
      }
      if (r.method === 'PATCH') {
        tasks = [{ ...task, state: 'RESOLVED' }];
        return json(tasks[0]);
      }
      return undefined;
    });
    render(
      <PatientRecords
        profile={profile}
        actor={actor}
        onChanged={vi.fn()}
        onDirtyChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('需要跟进什么？'), {
      target: { value: '核对报告' },
    });
    await userEvent.click(screen.getByRole('button', { name: '创建跟进任务' }));
    await screen.findByRole('heading', { name: '核对报告' });
    await userEvent.click(screen.getByRole('button', { name: '标记完成' }));
    expect(screen.getByRole('button', { name: '确认更新状态' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('处理说明'), {
      target: { value: '已查看并核对报告来源' },
    });
    await userEvent.click(screen.getByRole('button', { name: '确认更新状态' }));
    await waitFor(() =>
      expect(requests.some((r) => r.method === 'PATCH')).toBe(true),
    );
    expect(requests.find((r) => r.method === 'PATCH')?.body).toMatchObject({
      expected_state: 'PLANNED',
      state: 'RESOLVED',
      reason: '已查看并核对报告来源',
    });
    expect(requests.find((r) => r.method === 'POST')?.url.pathname).toContain(
      '/P-2001/tasks',
    );
  });
});
