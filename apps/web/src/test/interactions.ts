import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

export async function identify() {
  await userEvent.type(screen.getByLabelText('医生 ID'), 'DR-EXPLICIT');
  await userEvent.selectOptions(screen.getByLabelText('临床角色'), 'PHYSICIAN');
}
export async function createDraft() {
  await identify();
  await userEvent.type(screen.getByLabelText('就诊 ID'), 'ENC-REAL-9');
  await userEvent.click(screen.getByRole('button', { name: '生成交接草稿' }));
  return await screen.findByRole('textbox', { name: 'S · 当前情况' });
}
