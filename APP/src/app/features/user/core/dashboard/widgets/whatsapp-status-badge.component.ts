import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../../auth/auth.service';
import {
  IntegrationsApiService,
  WhatsAppStatus,
  whatsAppConnectionState,
} from '../../settings/integrations/integrations-api.service';

type BadgeStatus = 'checking' | 'unavailable' | 'connected' | 'error' | 'not_connected';

const DOT: Record<BadgeStatus, string> = {
  checking: 'bg-zinc-400 animate-pulse',
  unavailable: 'bg-zinc-400',
  connected: 'bg-emerald-500',
  error: 'bg-amber-500',
  not_connected: 'bg-red-500',
};

/** Same verbs + accents as the Integrations connector tile CTA. */
const CTA: Record<Exclude<BadgeStatus, 'checking'>, { label: string; classes: string }> = {
  unavailable: {
    label: 'View',
    classes: 'border border-subtle bg-surface text-default hover:bg-surface-2',
  },
  connected: {
    label: 'Manage',
    classes: 'border border-subtle bg-surface text-default hover:bg-surface-2',
  },
  error: { label: 'Reconnect', classes: 'bg-amber-500 text-white hover:bg-amber-600' },
  not_connected: { label: 'Connect', classes: 'bg-accent text-white hover:brightness-95' },
};

/**
 * Dashboard header badge — WhatsApp Business API connection status,
 * plus a button that opens the WhatsApp panel on the Integrations page
 * (`?connector=whatsapp`).
 *
 * Gated on `settings.integrations.manage`: `GET /whatsapp/status`
 * requires it server-side, and it is the same key that gates the
 * WhatsApp card the button lands on. Roles without it see nothing.
 */
@Component({
  selector: 'app-whatsapp-status-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
  template: `
    @if (canManage()) {
      <div class="mb-3 flex flex-wrap items-center gap-2" data-testid="whatsapp-status-badge">
        <span
          class="inline-flex items-center gap-2 rounded-full border border-subtle bg-surface py-1 pl-1 pr-3 text-[12px] shadow-sm"
          role="status"
          [attr.aria-label]="'WhatsApp Business API: ' + view().label"
        >
          <span
            class="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-white"
            aria-hidden="true"
          >
            <lucide-icon name="message-circle" size="12" />
          </span>
          <span class="font-medium text-default">WhatsApp Business API</span>
          <span class="inline-flex items-center gap-1.5 text-muted" aria-hidden="true">
            <span [class]="'inline-block h-1.5 w-1.5 rounded-full ' + DOT[view().status]"></span>
            {{ view().label }}
          </span>
          @if (view().status === 'connected' && phone(); as p) {
            <span class="hidden font-mono text-[11px] text-faint sm:inline">{{ p }}</span>
          }
        </span>
        @if (cta(); as c) {
          <a
            routerLink="/user/integrations"
            [queryParams]="{ connector: 'whatsapp' }"
            [class]="
              'inline-flex items-center gap-1 rounded-full px-3 py-1 text-[12px] font-semibold shadow-sm transition ' +
              c.classes
            "
            [attr.aria-label]="c.label + ' WhatsApp Business API in Integrations'"
          >
            {{ c.label }}
            <lucide-icon name="arrow-right" size="12" aria-hidden="true" />
          </a>
        }
      </div>
    }
  `,
})
export class WhatsAppStatusBadgeComponent {
  private readonly api = inject(IntegrationsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly DOT = DOT;

  protected readonly canManage = computed(() =>
    this.auth.hasPermission('settings.integrations.manage'),
  );

  /** `undefined` while loading, `null` when the status call failed. */
  private readonly status = signal<WhatsAppStatus | null | undefined>(undefined);

  protected readonly view = computed<{ status: BadgeStatus; label: string }>(() => {
    const s = this.status();
    if (s === undefined) return { status: 'checking', label: 'Checking…' };
    if (s === null) return { status: 'unavailable', label: 'Status unavailable' };
    return whatsAppConnectionState(s);
  });

  protected readonly phone = computed(
    () => this.status()?.display_phone_number ?? this.status()?.verified_name ?? null,
  );

  /** No button while checking — the verb would flip once the call lands. */
  protected readonly cta = computed(() => {
    const status = this.view().status;
    return status === 'checking' ? null : CTA[status];
  });

  constructor() {
    if (!this.canManage()) return;
    this.api
      .getWhatsAppStatus()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => this.status.set(s),
        error: () => this.status.set(null),
      });
  }
}
