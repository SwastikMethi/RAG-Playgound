import {writeFile, mkdir} from 'node:fs/promises';
import openapiTS, {astToString} from 'openapi-typescript';
import {compileFromFile} from 'json-schema-to-typescript';
await mkdir('apps/web/src/generated', {recursive:true});
await writeFile('apps/web/src/generated/api.ts', astToString(await openapiTS(new URL('../contracts/openapi.yaml', import.meta.url))));
await writeFile('apps/web/src/generated/trace.ts', await compileFromFile('contracts/trace-event.schema.json', {bannerComment:'/* Generated from contracts/trace-event.schema.json. */'}));
