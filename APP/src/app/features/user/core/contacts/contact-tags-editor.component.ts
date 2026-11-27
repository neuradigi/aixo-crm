import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { TagInputComponent } from '../shared/forms/tag-input.component';
import { injectContactTagSuggestions } from './contact-tag-suggestions';
import { ContactTagDelta, ContactsApiService } from './contacts-api.service';

/**
 * Inline "Contact tags" editor: every add / remove is saved at once via
 * `POST /contacts/{id}/tags` (a delta, so two people tagging the same
 * contact keep both changes). The chips always end up showing the
 * server's resulting list; a failed save restores the previous chips
 * and shows why. Read-only chips when `canEdit` is false.
 *
 *   <app-contact-tags-editor [contactId]="c.id" [tags]="c.tags"
 *     [canEdit]="canEditTags()" (tagsChange)="onTagsChanged($event)" />
 *
 * Pages that hold only the contact id (e.g. the inbox details rail) omit
 * `tags`; the editor then loads the contact itself and also goes
 * read-only for an anonymised contact.
 */
@Component({
  selector: 'app-contact-tags-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TagInputComponent],
  template: `
    @if (editable()) {
      <crm-tag-input
        [dense]="true"
        [ngModel]="current()"
        [suggestions]="vocabulary.suggestions()"
        [placeholder]="placeholder()"
        ariaLabel="Contact tags"
        (lookup)="vocabulary.search($event)"
        (added)="save({ add: [$event] })"
        (removed)="save({ remove: [$event] })"
      />
      @if (error(); as msg) {
        <p class="field-error mt-1">{{ msg }}</p>
      }
    } @else if (current().length > 0) {
      <div class="flex flex-wrap gap-1">
        @for (tag of current(); track tag) {
          <span
            class="inline-flex h-6 items-center rounded-full bg-surface-2 px-2.5 text-[12px] font-medium text-default ring-1 ring-subtle"
          >
            {{ tag }}
          </span>
        }
      </div>
    } @else {
      <span class="text-xs text-faint">No tags</span>
    }
  `,
})
export class ContactTagsEditorComponent {
  readonly contactId = input.required<string>();
  /** The contact's tags when the page already has them; `null` makes the
   *  editor load the contact. */
  readonly tags = input<readonly string[] | null>(null);
  readonly canEdit = input(false);
  readonly placeholder = input('Add a tag…');
  /** The contact's tags after each successful save. */
  readonly tagsChange = output<string[]>();

  protected readonly current = signal<string[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly vocabulary = injectContactTagSuggestions();
  /** Set when the editor loaded the contact itself and it is anonymised. */
  private readonly loadedAnonymised = signal(false);
  protected readonly editable = computed(() => this.canEdit() && !this.loadedAnonymised());

  private readonly api = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private loadSub: Subscription | null = null;

  constructor() {
    effect(() => {
      const id = this.contactId();
      const tags = this.tags();
      untracked(() => {
        this.error.set(null);
        if (tags !== null) {
          this.loadedAnonymised.set(false);
          this.current.set([...tags]);
        } else {
          this.load(id);
        }
      });
    });
    this.destroyRef.onDestroy(() => this.loadSub?.unsubscribe());
  }

  protected save(delta: ContactTagDelta): void {
    const previous = [...this.current()];
    this.error.set(null);
    this.api
      .updateTags(this.contactId(), delta)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.current.set(resp.tags);
          this.tagsChange.emit(resp.tags);
        },
        error: (err: HttpErrorResponse) => {
          // New array reference so the chip input re-renders the old list.
          this.current.set(previous);
          this.error.set(extractApiError(err) ?? "Couldn't update tags. Try again.");
        },
      });
  }

  private load(contactId: string): void {
    this.loadSub?.unsubscribe();
    this.current.set([]);
    this.loadSub = this.api.get(contactId).subscribe({
      next: (contact) => {
        this.loadedAnonymised.set(contact.anonymised_at != null);
        this.current.set([...contact.tags]);
      },
      error: () => this.error.set("Couldn't load this contact's tags."),
    });
  }
}
