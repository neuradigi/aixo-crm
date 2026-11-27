import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../shared/components/toast/toast.service';
import { FurnitureAuthService } from '../auth/auth.service';
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { AutoSendSummary, LeadsApiService } from './leads-api.service';

/** Plain-language "why" for skipped / failed / cancelled auto-messages.
 *  Codes are fixed on the server (`leads/auto_send`). */
const REASON_TEXT: Record<string, string> = {
  cancelled_by_user: 'cancelled by a colleague',
  replaced: 'replaced by a newer auto-message',
  lead_replied: 'the lead replied first',
  follow_up_closed: 'the follow-up was closed',
  follow_up_undated: 'the follow-up lost its date',
  follow_up_retyped: 'the follow-up type changed',
  too_late: 'it was more than 6 hours late',
  lead_closed: 'the lead is Won or Lost',
  template_unavailable: 'the template is no longer available',
  template_not_approved: 'the template is not approved by Meta',
  template_wrong_channel: 'the template no longer matches the channel',
  template_variables_missing: "the template's variables could not be filled",
  contact_missing: 'the contact no longer exists',
  contact_anonymised: 'the contact was anonymised',
  recipient_changed: "the contact's phone or email changed",
  org_read_only: 'the subscription is not active',
  sender_unavailable: 'the assigned person can no longer send messages',
  quiet_hours: 'it fell inside quiet hours',
  opted_out: 'the contact opted out',
  blocked: 'the number is on the block list',
  no_phone: 'the contact has no phone number',
  no_email: 'the contact has no email address',
  whatsapp_not_connected: 'WhatsApp is not connected',
  provider_rejected: 'WhatsApp refused it',
  rate_limited: 'WhatsApp kept rate-limiting it',
  render_failed: 'the email could not be filled in',
  mailbox_daily_cap: 'the mailbox reached its daily limit',
  missing_company_address: 'the company address is missing',
  interrupted: 'it was interrupted — it may or may not have gone out',
};

type Tone = 'accent' | 'success' | 'danger' | 'muted';

/**
 * Compact state of a follow-up's auto-message for follow-up lists:
 * scheduled (with time + Cancel), sending, sent (with delivery), not sent
 * (with the reason), cancelled. Cancel asks first, calls the API and
 * emits `changed` so the host list can refresh.
 */
@Component({
  selector: 'app-auto-send-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <span class="inline-flex max-w-full flex-wrap items-center gap-1.5 text-[11px]">
      <span
        class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ring-1"
        [class.bg-accent-soft]="tone() === 'accent'"
        [class.text-accent]="tone() === 'accent'"
        [class.ring-accent/20]="tone() === 'accent'"
        [class.bg-emerald-500/10]="tone() === 'success'"
        [class.text-emerald-700]="tone() === 'success'"
        [class.dark:text-emerald-300]="tone() === 'success'"
        [class.ring-emerald-500/20]="tone() === 'success'"
        [class.bg-red-500/10]="tone() === 'danger'"
        [class.text-red-600]="tone() === 'danger'"
        [class.dark:text-red-300]="tone() === 'danger'"
        [class.ring-red-500/20]="tone() === 'danger'"
        [class.bg-surface-2]="tone() === 'muted'"
        [class.text-muted]="tone() === 'muted'"
        [class.ring-subtle]="tone() === 'muted'"
        [attr.title]="reason()"
      >
        <lucide-icon [name]="icon()" class="h-3 w-3" aria-hidden="true" />
        {{ label() }}
      </span>
      @if (reason(); as why) {
        <span class="truncate text-faint">{{ why }}</span>
      }
      @if (canCancel()) {
        <button
          type="button"
          class="font-medium text-muted underline-offset-2 hover:text-default hover:underline disabled:opacity-50"
          [disabled]="cancelling()"
          (click)="cancel()"
        >
          {{ cancelling() ? 'Cancelling…' : 'Cancel' }}
        </button>
      }
    </span>
  `,
})
export class AutoSendBadgeComponent {
  readonly autoSend = input.required<AutoSendSummary>();
  /** The auto-send after a successful cancel. */
  readonly changed = output<AutoSendSummary>();

  private readonly api = inject(LeadsApiService);
  private readonly confirm = inject(ConfirmDialogService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly toast = inject(ToastService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly cancelling = signal(false);

  private readonly pending = computed(() => {
    const s = this.autoSend().status;
    return s === 'scheduled' || s === 'claimed';
  });

  protected readonly canCancel = computed(
    () => this.pending() && this.auth.hasPermission('conversations.write'),
  );

  protected readonly tone = computed<Tone>(() => {
    switch (this.autoSend().status) {
      case 'sent':
        return 'success';
      case 'failed':
      case 'skipped':
        return 'danger';
      case 'cancelled':
        return 'muted';
      default:
        return 'accent';
    }
  });

  protected readonly icon = computed(() => {
    switch (this.autoSend().status) {
      case 'sent':
        return 'check';
      case 'failed':
      case 'skipped':
        return 'alert-triangle';
      case 'cancelled':
        return 'x';
      default:
        return 'send';
    }
  });

  protected readonly label = computed(() => {
    const a = this.autoSend();
    switch (a.status) {
      case 'scheduled':
      case 'claimed': {
        const when = this.formatWhen(a.due_at);
        return `Auto-message${when ? ' ' + when : ''} · ${a.template_name}`;
      }
      case 'sending':
        return `Sending ${a.template_name}…`;
      case 'sent': {
        const delivery =
          a.delivery === 'read' ? ' · Read' : a.delivery === 'delivered' ? ' · Delivered' : '';
        return `Auto-message sent${delivery}`;
      }
      case 'cancelled':
        return 'Auto-message cancelled';
      default:
        return 'Auto-message not sent';
    }
  });

  protected readonly reason = computed<string | null>(() => {
    const a = this.autoSend();
    if (a.status !== 'failed' && a.status !== 'skipped' && a.status !== 'cancelled') return null;
    return a.reason ? (REASON_TEXT[a.reason] ?? null) : null;
  });

  protected async cancel(): Promise<void> {
    const a = this.autoSend();
    const ok = await this.confirm.ask({
      title: 'Cancel this auto-message?',
      body: `“${a.template_name}” won't be sent. The follow-up itself stays.`,
      confirmLabel: 'Cancel message',
      cancelLabel: 'Keep',
      danger: true,
    });
    if (!ok) return;
    this.cancelling.set(true);
    this.api
      .cancelAutoSend(a.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.cancelling.set(false);
          this.toast.success('Auto-message cancelled');
          this.changed.emit(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.cancelling.set(false);
          this.toast.error(extractApiError(err) ?? 'Could not cancel the auto-message.');
        },
      });
  }

  private formatWhen(value: string | null): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
}
