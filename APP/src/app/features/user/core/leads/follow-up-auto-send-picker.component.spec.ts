import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { TemplatesApiService } from '../templates/templates-api.service';
import { FollowUpAutoSendPickerComponent } from './follow-up-auto-send-picker.component';
import { AutoSendSummary, LeadsApiService } from './leads-api.service';

/**
 * follow-up-auto-send Steps 8 + 10 — the Update Status auto-send picker:
 * only usable templates are requested, an opted-out / address-less contact
 * blocks the picker, an existing scheduled message makes the choice wait
 * for Replace / Keep, and an own send time travels with the choice.
 */
describe('FollowUpAutoSendPickerComponent', () => {
  let fixture: ComponentFixture<FollowUpAutoSendPickerComponent>;
  let listCalls: unknown[];
  let pending: AutoSendSummary | null;

  const template = {
    id: 't1',
    name: 'Following up',
    body_text: 'Hi {{contact.first_name}}',
    body_html: null,
    subject: null,
  };

  function setup(contact: Record<string, unknown>, channel: 'whatsapp' | 'email' = 'whatsapp') {
    listCalls = [];
    TestBed.configureTestingModule({
      imports: [FollowUpAutoSendPickerComponent],
      providers: [
        {
          provide: TemplatesApiService,
          useValue: {
            list: (q: unknown) => {
              listCalls.push(q);
              return of({ items: [template], total: 1, limit: 200, offset: 0 });
            },
          },
        },
        { provide: LeadsApiService, useValue: { getPendingAutoSend: () => of(pending) } },
      ],
    });
    fixture = TestBed.createComponent(FollowUpAutoSendPickerComponent);
    fixture.componentRef.setInput('leadId', 'lead-1');
    fixture.componentRef.setInput('contact', contact);
    fixture.componentRef.setInput('channel', channel);
    fixture.componentRef.setInput('dueAt', '2030-01-01T10:30');
    fixture.detectChanges();
  }

  function pick(id: string): void {
    (fixture.componentInstance as unknown as { onPick(id: string): void }).onPick(id);
    fixture.detectChanges();
  }

  beforeEach(() => {
    pending = null;
  });

  it('asks only for published, active, Meta-approved WhatsApp templates', () => {
    setup({ phone: '+919000000001', whatsapp_opt_in_status: 'implicit' });
    expect(listCalls[0]).toEqual(
      jasmine.objectContaining({
        channel: 'whatsapp',
        internal_status: 'published',
        is_active: true,
        external_status: 'approved',
      }),
    );
  });

  it('emits the picked template with no decision needed', () => {
    setup({ phone: '+919000000001', whatsapp_opt_in_status: 'implicit' });
    pick('t1');
    expect(fixture.componentInstance.choice()).toEqual({
      templateId: 't1',
      replace: false,
      sendAt: null,
      needsInput: false,
    });
  });

  it('sends an own time when one is picked, starting from the follow-up time', () => {
    setup({ phone: '+919000000001', whatsapp_opt_in_status: 'implicit' });
    pick('t1');
    const picker = fixture.componentInstance as unknown as {
      onSendWhen(v: string): void;
      onCustomAt(v: string): void;
    };
    picker.onSendWhen('custom');
    expect(fixture.componentInstance.choice()?.sendAt).toBe(
      new Date('2030-01-01T10:30').toISOString(),
    );
    picker.onCustomAt('');
    expect(fixture.componentInstance.choice()?.needsInput).toBeTrue();
    picker.onCustomAt('2030-01-01T09:00');
    expect(fixture.componentInstance.choice()).toEqual({
      templateId: 't1',
      replace: false,
      sendAt: new Date('2030-01-01T09:00').toISOString(),
      needsInput: false,
    });
  });

  it('blocks the picker for an opted-out contact', () => {
    setup({ phone: '+919000000001', whatsapp_opt_in_status: 'opted_out' });
    expect(fixture.nativeElement.textContent).toContain('opted out of WhatsApp');
    pick('t1');
    expect(fixture.componentInstance.choice()).toBeNull();
  });

  it('waits for Replace when the person already has a scheduled message', () => {
    pending = {
      id: 'a1',
      task_id: 'task',
      lead_id: 'lead-2',
      status: 'scheduled',
      channel: 'whatsapp',
      template_name: 'Older',
      due_at: '2030-01-01T05:00:00Z',
      reason: null,
      created_by_id: 'u',
    };
    setup({ phone: '+919000000001', whatsapp_opt_in_status: 'implicit' });
    pick('t1');
    expect(fixture.componentInstance.choice()?.needsInput).toBeTrue();
    (fixture.componentInstance as unknown as { replaceExisting(): void }).replaceExisting();
    expect(fixture.componentInstance.choice()).toEqual({
      templateId: 't1',
      replace: true,
      sendAt: null,
      needsInput: false,
    });
  });
});
