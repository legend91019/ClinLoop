import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { json, serve } from './test/server';
import type { PatientProfile } from './api/workspaceTypes';

const profiles: PatientProfile[] = [1, 2].map((n) => ({
  patient_id: `P-200${n}`,
  encounter_id: `ENC-300${n}`,
  display_name: `模拟患者${n}`,
  sex: '女',
  age: 34,
  ward: '模拟病区',
  bed: `0${n}`,
  chief_complaint: '资料随访',
  history: '待补录',
  allergies: '待核对',
  admitted_at: null,
  synthetic: true,
  open_tasks: 1,
}));
const doc = {
  document_id: 'DOC-1',
  patient_id: 'P-2001',
  encounter_id: 'ENC-3001',
  kind: 'ROUND',
  title: '昨日查房草稿',
  content: '昨天记录的待办。',
  status: 'DRAFT',
  revision: 1,
  author_id: 'DR-TEST',
  created_at: '2026-10-26T08:00:00Z',
  updated_at: '2026-10-26T08:00:00Z',
  submitted_at: null,
  event_id: null,
};

function mockWorkspace() {
  return serve((r) => {
    if (r.url.pathname.endsWith('/patients')) return json(profiles);
    if (r.url.pathname.endsWith('/documents'))
      return json(r.url.pathname.includes('/P-2001/') ? [doc] : []);
    if (r.url.pathname.endsWith('/tasks')) return json([]);
    if (r.url.pathname.endsWith('/agent-workspace'))
      return json({ provider: 'mock', documents: [], tasks: [] });
    return undefined;
  });
}
async function go(name: string) {
  if (name === '患者列表' || name === '患者概览') {
    await userEvent.click(
      within(screen.getByRole('navigation', { name: '工作台导航' })).getByRole(
        'link',
        { name },
      ),
    );
    return;
  }
  const back = screen.queryByRole('button', { name: '返回患者概览' });
  if (back) await userEvent.click(back);
  else if (
    new URL(window.location.href).searchParams.get('view') !== 'overview'
  ) {
    await userEvent.click(
      within(screen.getByRole('navigation', { name: '工作台导航' })).getByRole(
        'link',
        { name: '患者概览' },
      ),
    );
  }
  await userEvent.click(
    screen.getByRole('button', { name: new RegExp('^' + name) }),
  );
}
async function identify() {
  await userEvent.type(screen.getByLabelText('医生 ID'), 'DR-TEST');
  await userEvent.selectOptions(screen.getByLabelText('临床角色'), 'PHYSICIAN');
}

describe('patient page navigation', () => {
  it('keeps patient features inside the overview and provides an explicit return action', async () => {
    mockWorkspace();
    window.history.replaceState(null, '', '/?patient=P-2001&view=overview');
    render(<App />);
    await screen.findByText('模拟患者1', { selector: 'dd' });
    const navigation = screen.getByRole('navigation', { name: '工作台导航' });
    expect(
      within(navigation)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['患者列表', '患者概览']);
    expect(
      within(navigation).queryByRole('link', { name: '病历与查房' }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^病历与查房/ }));
    expect(
      screen.getByRole('heading', { name: '病历与查房', level: 1 }),
    ).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '返回患者概览' }));
    expect(screen.getByRole('heading', { name: '基本信息' })).toBeVisible();
    expect(new URL(window.location.href).searchParams.get('patient')).toBe(
      'P-2001',
    );
    expect(new URL(window.location.href).searchParams.get('view')).toBe(
      'overview',
    );
    expect(
      screen.queryByRole('button', { name: '返回患者概览' }),
    ).not.toBeInTheDocument();
  });

  it('shows only the overview initially and keeps the directory on its own page', async () => {
    mockWorkspace();
    window.history.replaceState(null, '', '/?patient=P-2001');
    render(<App />);
    await screen.findByText('模拟患者1', { selector: 'dd' });
    const basics = screen.getByRole('region', { name: '患者档案' });
    for (const name of [
      '姓名',
      '性别',
      '民族',
      '年龄',
      '婚姻状况',
      '出生地',
      '职业',
      '入院时间',
    ]) {
      expect(within(basics).getByText(name)).toBeVisible();
    }
    expect(
      screen.queryByRole('textbox', { name: '患者 ID' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: /P-2001/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '患者概览', level: 1 }),
    ).toBeVisible();
    expect(
      screen.queryByRole('heading', { name: '我的患者' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: '病历与查房记录' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: '这位患者的 Agent 助手' }),
    ).not.toBeInTheDocument();
    await go('患者列表');
    expect(screen.getByRole('heading', { name: /我的患者/ })).toBeVisible();
    expect(
      screen.queryByRole('heading', { name: '模拟患者1' }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /模拟患者2/ }));
    expect(
      await screen.findByText('模拟患者2', { selector: 'dd' }),
    ).toBeVisible();
    expect(new URL(window.location.href).searchParams.get('patient')).toBe(
      'P-2002',
    );
    expect(new URL(window.location.href).searchParams.get('view')).toBe(
      'overview',
    );
  });

  it('retains unsaved document text and doctor identity when moving to another page and back', async () => {
    mockWorkspace();
    window.history.replaceState(null, '', '/?patient=P-2001&view=records');
    render(<App />);
    await screen.findByRole('button', { name: /昨日查房草稿/ });
    await identify();
    await userEvent.click(screen.getByRole('button', { name: /昨日查房草稿/ }));
    fireEvent.change(screen.getByLabelText('记录正文'), {
      target: { value: '尚未保存的今天查房内容' },
    });
    await go('患者 Agent 助手');
    expect(
      await screen.findByRole('heading', { name: '这位患者的 Agent 助手' }),
    ).toBeVisible();
    expect(
      screen.queryByRole('textbox', { name: '记录正文' }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/页面切换已为你保留/)).toBeVisible();
    await go('病历与查房');
    expect(screen.getByLabelText('记录正文')).toHaveValue(
      '尚未保存的今天查房内容',
    );
    expect(screen.getByLabelText('医生 ID')).toHaveValue('DR-TEST');
    expect(screen.getByLabelText('就诊 ID')).toHaveValue('ENC-3001');
    expect(new URL(window.location.href).searchParams.get('view')).toBe(
      'records',
    );
  });

  it('supports browser back/forward between pages without discarding the editor', async () => {
    mockWorkspace();
    window.history.replaceState(null, '', '/?patient=P-2001&view=records');
    render(<App />);
    await screen.findByRole('button', { name: /昨日查房草稿/ });
    await userEvent.click(screen.getByRole('button', { name: /昨日查房草稿/ }));
    fireEvent.change(screen.getByLabelText('记录正文'), {
      target: { value: '保留的草稿' },
    });
    await go('患者时间线');
    await act(async () => {
      window.history.back();
    });
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: '患者概览', level: 1 }),
      ).toBeVisible(),
    );
    await act(async () => {
      window.history.back();
    });
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: '病历与查房', level: 1 }),
      ).toBeVisible(),
    );
    expect(screen.getByLabelText('记录正文')).toHaveValue('保留的草稿');
    await act(async () => {
      window.history.forward();
    });
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: '患者概览', level: 1 }),
      ).toBeVisible(),
    );
    await act(async () => {
      window.history.forward();
    });
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: '患者时间线', level: 1 }),
      ).toBeVisible(),
    );
    expect(
      screen.queryByRole('textbox', { name: '记录正文' }),
    ).not.toBeInTheDocument();
  });

  it('guards a different-patient selection while preserving the current draft if cancelled', async () => {
    mockWorkspace();
    window.history.replaceState(null, '', '/?patient=P-2001&view=records');
    render(<App />);
    await screen.findByRole('button', { name: /昨日查房草稿/ });
    await userEvent.click(screen.getByRole('button', { name: /昨日查房草稿/ }));
    fireEvent.change(screen.getByLabelText('记录正文'), {
      target: { value: '患者1未保存内容' },
    });
    await go('患者列表');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await userEvent.click(screen.getByRole('button', { name: /模拟患者2/ }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(new URL(window.location.href).searchParams.get('patient')).toBe(
      'P-2001',
    );
    await go('病历与查房');
    expect(screen.getByLabelText('记录正文')).toHaveValue('患者1未保存内容');
    await go('患者列表');
    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole('button', { name: /模拟患者2/ }));
    await go('病历与查房');
    expect(
      screen.queryByDisplayValue('患者1未保存内容'),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('就诊 ID')).toHaveValue('ENC-3002');
  });

  it('follows a task to its trace page instead of scrolling a long page', async () => {
    mockWorkspace();
    window.history.replaceState(null, '', '/?patient=P-2001&view=loops');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByLabelText('就诊 ID')).toHaveValue('ENC-3001'),
    );
    await userEvent.click(
      await screen.findByRole('button', { name: '查看轨迹' }),
    );
    expect(
      await screen.findByRole('heading', { name: 'Agent 运行轨迹', level: 2 }),
    ).toBeVisible();
    expect(new URL(window.location.href).searchParams.get('view')).toBe(
      'trace',
    );
    expect(
      screen.queryByRole('heading', { name: '未闭环任务', level: 2 }),
    ).not.toBeInTheDocument();
  });
});
