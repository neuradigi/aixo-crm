import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
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
 */
@Component({
  selector: 'app-contact-tags-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TagInputComponent],
  template: `
    @if (canEdit()) {
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
  readonly tags = input.required<readonly string[]>();
  readonly canEdit = input(false);
  readonly placeholder = input('Add a tag…');
  /** The contact's tags after each successful save. */
  readonly tagsChange = output<string[]>();

  protected readonly current = signal<string[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly vocabulary = injectContactTagSuggestions();

  private readonly api = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  constructor() {
    effect(() => {
      const tags = this.tags();
      untracked(() => this.current.set([...tags]));
    });
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
}
