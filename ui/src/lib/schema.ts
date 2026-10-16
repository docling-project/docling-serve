/**
 * Turns the OpenAPI schema of `ConvertDocumentsOptions` into form field specs.
 * Deprecated fields are dropped, so legacy options never show up in the UI.
 */

type JsonSchema = {
  $ref?: string;
  type?: string | string[];
  enum?: unknown[];
  items?: JsonSchema;
  prefixItems?: JsonSchema[];
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  allOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  default?: unknown;
  description?: string;
  title?: string;
  deprecated?: boolean;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
};

export interface OpenApiDocument {
  components?: { schemas?: Record<string, JsonSchema> };
}

export type FieldControl =
  | "boolean"
  | "select"
  | "multiselect"
  | "number"
  | "integer"
  | "text"
  | "string-list"
  | "range"
  | "json";

export interface FieldSpec {
  name: string;
  label: string;
  description?: string;
  control: FieldControl;
  options?: string[];
  nullable: boolean;
  default?: unknown;
  minimum?: number;
  maximum?: number;
}

const OPTIONS_SCHEMA = "ConvertDocumentsOptions";

function resolve(schema: JsonSchema, doc: OpenApiDocument): JsonSchema {
  if (schema.$ref) {
    const name = schema.$ref.split("/").pop() ?? "";
    const target = doc.components?.schemas?.[name] ?? {};
    return { ...resolve(target, doc), ...withoutRef(schema) };
  }
  if (schema.allOf?.length === 1) {
    return { ...resolve(schema.allOf[0], doc), ...withoutAllOf(schema) };
  }
  return schema;
}

function withoutRef({ $ref: _ref, ...rest }: JsonSchema): JsonSchema {
  return rest;
}

function withoutAllOf({ allOf: _allOf, ...rest }: JsonSchema): JsonSchema {
  return rest;
}

function typeOf(schema: JsonSchema): string | undefined {
  return Array.isArray(schema.type) ? schema.type.find((t) => t !== "null") : schema.type;
}

function toField(name: string, raw: JsonSchema, doc: OpenApiDocument): FieldSpec {
  const outer = resolve(raw, doc);
  const variants = (outer.anyOf ?? outer.oneOf ?? [outer]).map((v) => resolve(v, doc));
  const nonNull = variants.filter((v) => typeOf(v) !== "null" && v.type !== "null");
  const nullable = nonNull.length < variants.length;
  const base: FieldSpec = {
    name,
    label: outer.title ?? name,
    description: outer.description,
    control: "json",
    nullable,
    default: outer.default,
  };

  if (nonNull.length !== 1) return base;
  const schema = nonNull[0];
  const type = typeOf(schema);

  if (schema.enum) {
    return { ...base, control: "select", options: schema.enum.map(String) };
  }
  if (type === "boolean") return { ...base, control: "boolean" };
  if (type === "integer" || type === "number") {
    return {
      ...base,
      control: type,
      minimum: schema.minimum ?? schema.exclusiveMinimum,
      maximum: schema.maximum ?? schema.exclusiveMaximum,
    };
  }
  if (type === "string") return { ...base, control: "text" };
  if (type === "array") {
    if (schema.prefixItems?.length === 2) return { ...base, control: "range" };
    const items = schema.items ? resolve(schema.items, doc) : {};
    if (items.enum) return { ...base, control: "multiselect", options: items.enum.map(String) };
    if (typeOf(items) === "string") return { ...base, control: "string-list" };
  }
  return base;
}

export function optionFields(doc: OpenApiDocument | null): FieldSpec[] {
  const schema = doc?.components?.schemas?.[OPTIONS_SCHEMA];
  if (!doc || !schema?.properties) return [];
  return Object.entries(schema.properties)
    .filter(([, property]) => !property.deprecated)
    .map(([name, property]) => toField(name, property, doc));
}
