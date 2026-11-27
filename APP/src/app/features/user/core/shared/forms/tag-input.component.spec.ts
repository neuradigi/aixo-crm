import { CdkConnectedOverlay } from '@angular/cdk/overlay';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { TagInputComponent } from './tag-input.component';

/**
 * contact-tags-for-campaigns Step 3 — `crm-tag-input` behaviour:
 * case-snapping to an existing spelling, committing typed text on blur,
 * the count / length limits, markup rendered as plain text, and the open
 * panel following the box when a container scrolls.
 */
describe('TagInputComponent', () => {
  let fixture: ComponentFixture<TagInputComponent>;
  let changes: string[][];

  function input(): HTMLInputElement {
    return fixture.nativeElement.querySelector('input[role="combobox"]') as HTMLInputElement;
  }

  function type(value: string): void {
    input().value = value;
    input().dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  function press(key: string): void {
    input().dispatchEvent(new KeyboardEvent('keydown', { key }));
    fixture.detectChanges();
  }

  function chips(): string[] {
    return Array.from(fixture.nativeElement.querySelectorAll('span.rounded-full > span')).map(
      (el) => ((el as HTMLElement).textContent ?? '').trim(),
    );
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [TagInputComponent] });
    fixture = TestBed.createComponent(TagInputComponent);
    changes = [];
    fixture.componentInstance.registerOnChange((v) => changes.push(v));
    fixture.componentRef.setInput('suggestions', [{ value: 'Hot', count: 3 }]);
    fixture.detectChanges();
  });

  it('snaps a typed tag to the existing spelling ignoring case', () => {
    type('hot');
    press('Enter');
    expect(chips()).toEqual(['Hot']);
    expect(changes.at(-1)).toEqual(['Hot']);
  });

  it('commits typed text on blur', () => {
    type('sofa');
    input().dispatchEvent(new Event('blur'));
    fixture.detectChanges();
    expect(chips()).toEqual(['sofa']);
  });

  it('adds every comma-separated part of pasted text', () => {
    type('sofa, chair,');
    expect(chips()).toEqual(['sofa', 'chair']);
  });

  it('refuses a tag past the count limit and keeps the text', () => {
    fixture.componentRef.setInput('maxTags', 1);
    fixture.componentInstance.writeValue(['vip']);
    fixture.detectChanges();
    type('sofa');
    press('Enter');
    expect(chips()).toEqual(['vip']);
    expect(input().value).toBe('sofa');
    expect(fixture.nativeElement.textContent).toContain('at most 1 tags');
  });

  it('refuses a tag longer than the length limit', () => {
    type('x'.repeat(65));
    press('Enter');
    expect(chips()).toEqual([]);
    expect(fixture.nativeElement.textContent).toContain('at most 64 characters');
  });

  it('removes the last chip on Backspace in an empty box', () => {
    fixture.componentInstance.writeValue(['a', 'b']);
    fixture.detectChanges();
    press('Backspace');
    expect(chips()).toEqual(['a']);
  });

  it('keeps the open panel under the box when a container scrolls', () => {
    input().dispatchEvent(new Event('focus'));
    fixture.detectChanges();
    const overlay = fixture.debugElement
      .queryAllNodes(By.directive(CdkConnectedOverlay))[0]
      .injector.get(CdkConnectedOverlay);
    const update = spyOn(overlay.overlayRef, 'updatePosition');
    const scroller = document.createElement('div');
    document.body.appendChild(scroller);
    scroller.dispatchEvent(new Event('scroll'));
    scroller.remove();
    expect(update).toHaveBeenCalled();
  });

  it('renders markup in a tag as text', () => {
    fixture.componentInstance.writeValue(['<b>x</b>']);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('b')).toBeNull();
    expect(chips()).toEqual(['<b>x</b>']);
  });
});
