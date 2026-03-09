export type IntervalUnit = 'minutes' | 'hours' | 'days' | 'weeks';

export function parseInterval(seconds: number): { value: string; unit: IntervalUnit } {
  if (seconds === 0) {
    return { value: '0', unit: 'minutes' };
  }
  if (seconds >= 604800 && seconds % 604800 === 0) {
    return { value: String(seconds / 604800), unit: 'weeks' };
  }
  if (seconds >= 86400 && seconds % 86400 === 0) {
    return { value: String(seconds / 86400), unit: 'days' };
  }
  if (seconds >= 3600 && seconds % 3600 === 0) {
    return { value: String(seconds / 3600), unit: 'hours' };
  }
  return { value: String(seconds / 60), unit: 'minutes' };
}

export function formatScheduleExplainer(
  runAt: string,
  intervalValue: string,
  intervalUnit: IntervalUnit,
  maxRuns: string
): string {
  const interval = parseInt(intervalValue) || 0;
  const hasRunAt = runAt !== '';
  const runs = maxRuns ? parseInt(maxRuns) : null;

  const formatRunAt = (val: string) => {
    const d = new Date(val);
    return d.toLocaleString(undefined, {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  const pluralize = (n: number, unit: string) => {
    if (n === 1) {
      const singular: Record<string, string> = {
        minutes: 'minute',
        hours: 'hour',
        days: 'day',
        weeks: 'week',
      };
      return singular[unit] || unit;
    }
    return `${n} ${unit}`;
  };

  const runsSuffix = runs ? `, then stop after ${runs} run${runs === 1 ? '' : 's'}` : '';

  if (hasRunAt && interval === 0) {
    return `Runs once on ${formatRunAt(runAt)}`;
  }

  if (hasRunAt && interval > 0) {
    return `First run on ${formatRunAt(runAt)}, then every ${pluralize(interval, intervalUnit)}${runsSuffix}`;
  }

  if (interval > 0) {
    return `Runs immediately, then every ${pluralize(interval, intervalUnit)}${runsSuffix}`;
  }

  return 'Set an interval or a specific date/time to schedule this task';
}

export function isoToDatetimeLocal(iso: string): string {
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function datetimeLocalToIso(local: string): string {
  return new Date(local).toISOString();
}
