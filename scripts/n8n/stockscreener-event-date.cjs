module.exports = String.raw`function stockscreenerEventDate(timestamp){
const value=String(timestamp||"");
const match=value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/i);
const parsed=Date.parse(value);
if(!match||!Number.isFinite(parsed))throw Error("invalid_schedule_timestamp");
const [,year,month,day,hour,minute,second]=match;
const local=new Date(Date.UTC(Number(year),Number(month)-1,Number(day),Number(hour),Number(minute),Number(second)));
if(local.getUTCFullYear()!==Number(year)||local.getUTCMonth()+1!==Number(month)||local.getUTCDate()!==Number(day)||local.getUTCHours()!==Number(hour)||local.getUTCMinutes()!==Number(minute)||local.getUTCSeconds()!==Number(second))throw Error("invalid_schedule_timestamp");
const parts=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Taipei",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date(parsed));
const part=type=>parts.find(item=>item.type===type)?.value;
const date=[part("year"),part("month"),part("day")].join("-");
if(!/^\d{4}-\d{2}-\d{2}$/.test(date))throw Error("invalid_schedule_timestamp");
return date;
}`;
