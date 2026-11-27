import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ToastService } from '../../../../shared/components/toast/toast.service';
import { FurnitureAuthService } from '../auth/auth.service';
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { AutoSendBadgeComponent } from './auto-send-badge.component';
import { AutoSendSummary, LeadsApiService } from './leads-api.service';

/**
 * follow-up-auto-send Step 9 — the auto-message badge on follow-up lists:
 * each state reads in plain language, Cancel needs `conversations.write`
 * and a confirm, and a cancel hands the new state back to the list.
 */
describe('AutoSendBadgeComponent', () => {
  let fixture: ComponentFixture<AutoSendBadgeComponent>;
  let canWrite: boolean;
  let confirmed: boolean;
  let cancelCalls: string[];

  const base: AutoSendSummary = {
    id: 'a1',
    task_id: 'task-1',
    lead_id: 'lead-1',
    status: 'scheduled',
    channel: 'whatsapp',
    template_name: 'Following up',
    due_at: '2030-01-01T05:00:00Z',
    reason: null,
    created_by_id: 'u1',
  };

  function setup(autoSend: AutoSendSummary): void {
    cancelCalls = [];
    TestBed.configureTestingModule({
      imports: [AutoSendBadgeComponent],
      providers: [
        { provide: FurnitureAuthService, useValue: { hasPermission: () => canWrite } },
        { provide: ConfirmDialogService, useValue: { ask: () => Promise.resolve(confirmed) } },
        { provide: ToastService, useValue: { success: () => undefined, error: () => undefined } },
        {
          provide: LeadsApiService,
          useValue: {
            cancelAutoSend: (id: string) => {
              cancelCalls.push(id);
              return of({ ...base, status: 'cancelled', reason: 'cancelled_by_user' });
            },
          },
        },
      ],
    });
    fixture = TestBed.createComponent(AutoSendBadgeComponent);
    fixture.componentRef.setInput('autoSend', autoSend);
    fixture.detectChanges();
  }

  function text(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function cancelButton(): HTMLButtonElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector('button');
  }

  beforeEach(() => {
    canWrite = true;
    confirmed = true;
  });

  it('shows a scheduled message with its template and a Cancel button', () => {
    setup(base);
    expect(text()).toContain('Following up');
    expect(cancelButton()?.textContent).toContain('Cancel');
  });

  it('hides Cancel without conversations.write', () => {
    canWrite = false;
    setup(base);
    expect(cancelButton()).toBeNull();
  });

  it('shows how far a sent message got', () => {
    setup({ ...base, status: 'sent', delivery: 'read' });
    expect(text()).toContain('Sent · Read');
    expect(text()).toContain('Following up');
    expect(cancelButton()).toBeNull();
  });

  it('explains why a message was not sent', () => {
    setup({ ...base, status: 'skipped', reason: 'opted_out' });
    expect(text()).toContain('Not sent');
    expect(text()).toContain('the contact opted out');
  });

  it('cancels after confirming and emits the new state', async () => {
    setup(base);
    const emitted: AutoSendSummary[] = [];
    fixture.componentInstance.changed.subscribe((a) => emitted.push(a));
    cancelButton()?.click();
    await fixture.whenStable();
    expect(cancelCalls).toEqual(['a1']);
    expect(emitted[0]?.status).toBe('cancelled');
  });

  it('does nothing when the confirm is declined', async () => {
    confirmed = false;
    setup(base);
    cancelButton()?.click();
    await fixture.whenStable();
    expect(cancelCalls).toEqual([]);
  });
});
