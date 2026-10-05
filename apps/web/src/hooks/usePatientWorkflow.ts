import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

export interface Resource<T> {
  data: T | undefined;
  loading: boolean;
  error: string | null;
  retry: () => void;
  setData: (data: T) => void;
}
export function useResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
): Resource<T> {
  const [state, setState] = useState<{
    data: T | undefined;
    loading: boolean;
    error: string | null;
  }>({ data: undefined, loading: true, error: null });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setState({ data: undefined, loading: true, error: null });
    load(controller.signal).then(
      (data) => {
        if (current) setState({ data, loading: false, error: null });
      },
      (error) => {
        if (current)
          setState({
            data: undefined,
            loading: false,
            error: error instanceof Error ? error.message : '请求失败，请重试',
          });
      },
    );
    return () => {
      current = false;
      controller.abort();
    };
  }, [load, revision]);
  return {
    ...state,
    retry: useCallback(() => setRevision((value) => value + 1), []),
    setData: useCallback(
      (data: T) => setState({ data, loading: false, error: null }),
      [],
    ),
  };
}

export function useAlive() {
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  return alive;
}

export function usePatientWorkflow(patient: string, hours: number) {
  const timeline = useResource(
    useCallback(
      async (signal: AbortSignal) => {
        const result = await api.listTimeline(patient, hours, signal);
        if (result.patient_id !== patient)
          throw new Error('时间线与当前患者不匹配');
        return result;
      },
      [patient, hours],
    ),
  );
  const loops = useResource(
    useCallback(
      (signal: AbortSignal) => api.listLoops(patient, signal),
      [patient],
    ),
  );
  const findings = useResource(
    useCallback(
      async (signal: AbortSignal) => {
        const result = await api.listFindings(patient, signal);
        if (result.some((item) => item.patient_id !== patient))
          throw new Error('流程缺口与当前患者不匹配');
        return result;
      },
      [patient],
    ),
  );
  return { timeline, loops, findings };
}
