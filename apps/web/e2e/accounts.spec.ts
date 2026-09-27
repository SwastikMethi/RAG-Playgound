import { test, expect } from '@playwright/test';

// Browser interaction uses the real rendered screens with an explicit auth API fixture.
// Real sessions, hashing, recovery and ownership are exercised in test_hosted.py.
for (const width of [1440, 1024, 390]) test(`account signup and recovery at ${width}px`, async ({ page }) => {
  await page.setViewportSize({width, height: width === 390 ? 844 : 900});
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.route('**/api/v1/auth/me', route => route.fulfill({json: {deployment:'hosted', user:null, csrf_token:null, turnstile_site_key:'fixture-site'}}));
  await page.route('https://challenges.cloudflare.com/**', route => route.fulfill({contentType:'application/javascript', body:`window.turnstile={render:(node,opts)=>{opts.callback('fixture-token');return 'widget';},remove:()=>{},reset:()=>{}};window.dispatchEvent(new Event('turnstile-ready'));`}));
  await page.route('**/api/v1/auth/register', async route => {
    expect(route.request().postDataJSON().username).toBe('playground-user');
    await route.fulfill({status:201,json:{user:{id:'fixture-user',username:'playground-user'},csrf_token:'c'.repeat(64), recovery_code:'r'.repeat(43)}});
  });
  await page.goto('/signup');
  await expect(page.getByRole('heading',{name:'Create your account'})).toBeVisible();
  await page.getByLabel('Username', {exact:true}).fill('playground-user');
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Password', {exact:true})).toBeFocused();
  await page.getByLabel('Password', {exact:true}).fill('a long private passphrase');
  await page.getByRole('button',{name:'Create account',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Save your recovery code'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Continue to workspace'})).toBeDisabled();
  await page.getByLabel('I saved my recovery code').check();
  expect((await page.getByLabel('I saved my recovery code').boundingBox())?.width).toBeLessThanOrEqual(24);
  await expect(page.getByRole('button',{name:'Continue to workspace'})).toBeEnabled();
  await page.screenshot({path:`.data/release/hosted/recovery-${width}.png`,fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.goto('/login');
  await expect(page.getByRole('heading',{name:'Sign in to your workspace'})).toBeVisible();
  await page.screenshot({path:`.data/release/hosted/login-${width}.png`,fullPage:true});
  await page.getByRole('link',{name:'Recover your account'}).click();
  await expect(page.getByLabel('Recovery code',{exact:true})).toBeVisible();
});

for (const width of [1440, 390]) test(`private key setup and errors at ${width}px`, async ({page}) => {
  await page.setViewportSize({width, height: width === 390 ? 844 : 900});
  await page.route('**/api/v1/auth/me', route => route.fulfill({json:{deployment:'hosted',user:{id:'fixture-user',username:'playground-user'},csrf_token:'c'.repeat(64),turnstile_site_key:'fixture-site'}}));
  let configured = false, reject = true;
  await page.route('**/api/v1/me/openai-key', async route => {
    if (route.request().method() === 'GET') { await route.fulfill({json:{configured}}); return; }
    expect(route.request().headers()['x-csrf-token']).toBe('c'.repeat(64));
    if (reject) { reject=false; await route.fulfill({status:429,json:{error:{message:'Too many attempts. Try again later.'}}}); return; }
    configured = route.request().method() === 'PUT';
    await route.fulfill({status:204});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Setup',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your OpenAI key'})).toBeVisible();
  await page.getByLabel('OpenAI API key').fill('sk-ui-fixture-key');
  expect(await page.getByLabel('OpenAI API key').getAttribute('type')).toBe('password');
  await page.getByRole('button',{name:'Save key',exact:true}).click();
  await expect(page.getByText('Too many attempts. Try again later.')).toBeVisible();
  await page.screenshot({path:`.data/release/hosted/key-error-${width}.png`,fullPage:true});
  await page.getByRole('button',{name:'Save key',exact:true}).click();
  await expect(page.getByLabel('OpenAI API key')).toHaveValue('');
  await expect(page.getByText('A key is saved for your account.',{exact:false})).toBeVisible();
  await page.getByText('Change password',{exact:true}).click();
  await expect(page.getByLabel('Current password',{exact:true})).toBeVisible();
  await page.screenshot({path:`.data/release/hosted/key-saved-${width}.png`,fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole('button',{name:'Remove key',exact:true}).click();
  await expect(page.getByText('Key removed. New model jobs need a key.')).toBeVisible();
});
