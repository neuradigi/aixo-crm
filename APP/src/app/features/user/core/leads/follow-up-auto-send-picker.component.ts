import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  model,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { catchError, of } from 'rxjs';

import { Contact } from '../contacts/contacts-api.service';
import { MobileSelectComponent, MobileSelectOption } from '../shared/forms/mobile-select.component';
import { TemplateRead, TemplatesApiService } from '../templates/templates-api.service';
import { AutoSendSummary, LeadsApiService } from './leads-api.service';

export type AutoSendChannel = 'whatsapp' | 'email';

/** What the Update Status modal sends with the follow-up. */
export interface AutoSendChoice {
  templateId: string;
  replace: boolean;
  /** The person already has a scheduled auto-message and the user has
   *  not yet chosen Replace or Keep — the modal blocks Save meanwhile. */
  decisionPending: boolean;
}

const TEMPLATE_LIMIT = 200;

/**
 * "Auto-send template (optional)" for a WhatsApp / Email follow-up in the
 * Update Status modal: lists only templates that can actually be sent,
 * previews the chosen one (email HTML inside a sandboxed iframe), says
 * when it will go, and — when this person already has an auto-message
 * scheduled — asks Replace or Keep before Save.
 */
@Component({
  selector: 'app-follow-up-auto-send-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, MobileSelectComponent],
  template: `
    <div class="rounded-lg border border-subtle bg-surface-2/40 p-3">
      <div class="flex items-center gap-1.5">
        <lucide-icon name="send" class="h-3.5 w-3.5 text-muted" />
        <span class="text-xs font-medium text-default">Auto-send template</span>
        <span class="text-xs text-faint">(optional)</span>
      </div>

      @if (blockedReason(); as reason) {
        <p class="mt-2 text-xs text-muted">{{ reason }}</p>
      } @else {
        <crm-mobile-select
          class="mt-1.5 block"
          [options]="options()"
          [value]="templateId()"
          [searchable]="true"
          searchPlaceholder="Search templates…"
          [placeholder]="placeholder()"
          ariaLabel="Auto-send template"
          (valueChange)="onPick($event)"
        />

        @if (selected(); as t) {
          <div class="mt-2 overflow-hidden rounded-md border border-subtle bg-surface">
            @if (channel() === 'email' && t.body_html) {
              @if (t.subject) {
                <p class="border-b border-subtle px-3 py-1.5 text-xs text-default">
                  <span class="text-faint">Subject:</span> {{ t.subject }}
                </p>
              }
              <iframe
                class="block h-40 w-full bg-white"
                sandbox=""
                title="Email template preview"
                [srcdoc]="t.body_html"
              ></iframe>
            } @else {
              <p
                class="max-h-40 overflow-y-auto whitespace-pre-wrap px-3 py-2 text-xs text-default"
              >
                {{ t.body_text }}
              </p>
            }
          </div>
          @if (sendAtLabel(); as when) {
            <p class="mt-1.5 flex items-center gap-1 text-xs text-muted">
              <lucide-icon name="clock" class="h-3 w-3" />
              Will send {{ when }}. Cancel any time from Follow-Up Status.
            </p>
          }
        } @else {
          <p class="mt-1.5 text-xs text-muted">
            Pick a template to send it automatically at the follow-up time.
          </p>
        }

        @if (selected() && pending(); as existing) {
          <div
            class="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-default"
          >
            @if (replaceChosen()) {
              <p>
                Will replace “{{ existing.template_name }}” scheduled for
                {{ formatWhen(existing.due_at) }}.
              </p>
            } @else {
              <p>
                This person already has “{{ existing.template_name }}” scheduled for
                {{ formatWhen(existing.due_at) }}.
              </p>
              <div class="mt-2 flex gap-2">
                <button type="button" class="btn btn-secondary btn-sm" (click)="keepExisting()">
                  Keep existing
                </button>
                <button type="button" class="btn btn-primary btn-sm" (click)="replaceExisting()">
                  Replace it
                </button>
              </div>
            }
          </div>
        }
      }

      @if (serverError(); as err) {
        <p class="mt-2 text-xs text-red-500">{{ err }}</p>
      }
    </div>
  `,
})
export class FollowUpAutoSendPickerComponent {
  readonly leadId = input.required<string>();
  readonly contact = input<Contact | null>(null);
  readonly channel = input<AutoSendChannel | null>(null);
  /** The follow-up time as the date picker emits it (local, no zone). */
  readonly dueAt = input<string>('');
  /** Auto-send error from the last save, shown under the picker. */
  readonly serverError = input<string | null>(null);
  readonly choice = model<AutoSendChoice | null>(null);

  private readonly templatesApi = inject(TemplatesApiService);
  private readonly leadsApi = inject(LeadsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly templateId = signal('');
  protected readonly replaceChosen = signal(false);
  protected readonly loading = signal(false);
  protected readonly pending = signal<AutoSendSummary | null>(null);
  private readonly templatesByChannel = signal<Partial<Record<AutoSendChannel, TemplateRead[]>>>(
    {},
  );

  protected readonly templates = computed<TemplateRead[]>(() => {
    const ch = this.channel();
    return ch ? (this.templatesByChannel()[ch] ?? []) : [];
  });

  protected readonly options = computed<MobileSelectOption[]>(() => [
    { value: '', label: "Don't send automatically" },
    ...this.templates().map((t) => ({ value: t.id, label: t.name })),
  ]);

  protected readonly placeholder = computed(() =>
    this.loading() ? 'Loading templates…' : 'Choose a template',
  );

  protected readonly selected = computed<TemplateRead | null>(
    () => this.templates().find((t) => t.id === this.templateId()) ?? null,
  );

  /** Why nothing can be auto-sent to this contact on this channel. */
  protected readonly blockedReason = computed<string | null>(() => {
    const c = this.contact();
    const ch = this.channel();
    if (!c || !ch) return null;
    if (c.anonymised_at) return 'This contact was anonymised and can no longer be messaged.';
    if (ch === 'whatsapp') {
      if (!c.phone) return 'Add a phone number to the contact to send WhatsApp automatically.';
      if (c.whatsapp_opt_in_status === 'opted_out') {
        return 'This contact has opted out of WhatsApp.';
      }
    } else {
      if (!c.email) return 'Add an email address to the contact to send email automatically.';
      if (c.email_opt_in_status === 'opted_out') return 'This contact has opted out of email.';
    }
    return null;
  });

  protected readonly sendAtLabel = computed<string | null>(() =>
    this.dueAt() ? this.formatWhen(this.dueAt()) : null,
  );

  constructor() {
    // Templates for the follow-up's channel, fetched once per channel.
    effect(() => {
      const ch = this.channel();
      if (ch && !untracked(() => this.templatesByChannel()[ch])) this.loadTemplates(ch);
    });

    // A different channel means the picked template no longer applies.
    effect(() => {
      this.channel();
      untracked(() => this.reset());
    });

    // The person's existing scheduled auto-message, if any.
    effect(() => {
      const id = this.leadId();
      untracked(() =>
        this.leadsApi
          .getPendingAutoSend(id)
          .pipe(
            catchError(() => of(null)),
            takeUntilDestroyed(this.destroyRef),
          )
          .subscribe((pending) => {
            this.pending.set(pending);
            this.emit();
          }),
      );
    });
  }

  protected onPick(id: string): void {
    this.templateId.set(id);
    this.replaceChosen.set(false);
    this.emit();
  }

  protected keepExisting(): void {
    this.onPick('');
  }

  protected replaceExisting(): void {
    this.replaceChosen.set(true);
    this.emit();
  }

  protected formatWhen(value: string | null): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString(undefined, {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  private reset(): void {
    this.templateId.set('');
    this.replaceChosen.set(false);
    this.emit();
  }

  private emit(): void {
    const id = this.templateId();
    if (!id || this.blockedReason()) {
      this.choice.set(null);
      return;
    }
    const hasPending = this.pending() !== null;
    this.choice.set({
      templateId: id,
      replace: hasPending && this.replaceChosen(),
      decisionPending: hasPending && !this.replaceChosen(),
    });
  }

  private loadTemplates(channel: AutoSendChannel): void {
    this.loading.set(true);
    this.templatesApi
      .list({
        channel,
        internal_status: 'published',
        is_active: true,
        ...(channel === 'whatsapp' ? { external_status: 'approved' as const } : {}),
        sort: 'name',
        limit: TEMPLATE_LIMIT,
      })
      .pipe(
        catchError(() => of({ items: [] as TemplateRead[] })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => {
        this.templatesByChannel.update((all) => ({ ...all, [channel]: resp.items }));
        this.loading.set(false);
      });
  }
}
