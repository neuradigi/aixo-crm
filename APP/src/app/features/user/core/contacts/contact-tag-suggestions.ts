import { Signal, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject, catchError, debounceTime, of, switchMap } from 'rxjs';

import { TagSuggestion } from '../shared/forms/tag-input.component';
import { ContactsApiService } from './contacts-api.service';

/** Suggestions fetched per keystroke search; an empty query loads the
 *  endpoint's default (whole vocabulary). */
const SEARCH_LIMIT = 50;

export interface ContactTagSuggestions {
  readonly suggestions: Signal<TagSuggestion[]>;
  /** Feed `crm-tag-input`'s `(lookup)` output here. */
  search(q: string): void;
}

/**
 * Contact-tag vocabulary for a `crm-tag-input`, looked up server-side
 * (debounced, latest query wins, failures leave the list empty). Call
 * from a component field initializer — it needs an injection context.
 */
export function injectContactTagSuggestions(): ContactTagSuggestions {
  const api = inject(ContactsApiService);
  const suggestions = signal<TagSuggestion[]>([]);
  const query$ = new Subject<string>();

  query$
    .pipe(
      debounceTime(200),
      switchMap((q) =>
        api.listTags(q ? { q, limit: SEARCH_LIMIT } : {}).pipe(catchError(() => of({ tags: [] }))),
      ),
      takeUntilDestroyed(),
    )
    .subscribe((resp) => suggestions.set(resp.tags.map((o) => ({ value: o.tag, count: o.count }))));

  return { suggestions: suggestions.asReadonly(), search: (q) => query$.next(q) };
}
