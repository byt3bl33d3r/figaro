import { useState } from 'react';
import { ScheduleFormModal } from './ScheduleFormModal';

export function ScheduleButton() {
  const [isModalOpen, setIsModalOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setIsModalOpen(true)}
        className="px-3 py-1.5 bg-cctv-accent text-cctv-bg font-medium text-sm rounded hover:bg-cctv-accent-dim transition-colors flex items-center gap-1.5"
      >
        <svg
          className="w-4 h-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        Schedule
      </button>

      {isModalOpen && <ScheduleFormModal onClose={() => setIsModalOpen(false)} />}
    </>
  );
}
